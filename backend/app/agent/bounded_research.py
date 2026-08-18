"""Bounded research worker used by the production ``research_agent`` capability.

The worker is intentionally not a free-running tool loop.  Its job is context
isolation: plan the minimum evidence batch once, execute those Host-owned tools in
parallel, optionally fetch the top authoritative Web source, then compress the
observed evidence into ``ResearchFindings`` in one final model call.
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any, Literal, cast, get_args

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.common_tools.web_fetch import WebFetchLocalTool
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import KnownModelName, Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage

from app.agent.agents.research_agent import (
    EvidenceClaim,
    EvidenceSource,
    EvidenceToolName,
    ResearchFindings,
    ResearchRequest,
    VerificationResult,
)
from app.agent.context.runtime_clock import runtime_clock_context
from app.agent.research_runtime import (
    ResearchEvidenceTrace,
    ResearchUsageObservation,
    _result_is_usable,
    attest_research_findings,
    get_research_request_state,
    record_research_tool_observation,
)
from app.agent.tools._timeout import bound_tool_execution
from app.agent.tools.poi import search_poi
from app.agent.tools.route import search_maps
from app.agent.tools.weather import get_weather
from app.agent.tools.web_search import search_web
from app.core.config import settings

_MAX_PLAN_ACTIONS = 12
_MAX_AUTH_FETCHES = 2
_WEB_RESULT_COUNT = 3
_WEB_SNIPPET_LENGTH = 200
_FETCH_CONTENT_CHARS = 8_000


class WebSearchAction(BaseModel):
    tool: Literal["search_web"] = "search_web"
    item_ids: list[str] = Field(min_length=1, max_length=2)
    query: str = Field(min_length=1, max_length=100)
    authoritative: bool = False


class RouteAction(BaseModel):
    tool: Literal["search_maps"] = "search_maps"
    item_ids: list[str] = Field(min_length=1, max_length=2)
    origin: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=120)
    mode: Literal["driving", "transit"] = "transit"


class WeatherAction(BaseModel):
    tool: Literal["get_weather"] = "get_weather"
    item_ids: list[str] = Field(min_length=1, max_length=2)
    city: str = Field(min_length=1, max_length=80)
    forecast: bool = False


class PoiSearchAction(BaseModel):
    tool: Literal["search_poi"] = "search_poi"
    item_ids: list[str] = Field(min_length=1, max_length=2)
    keywords: str = Field(min_length=1, max_length=80)
    region: str | None = Field(default=None, max_length=80)
    strict_region: bool = False


ResearchAction = Annotated[
    WebSearchAction | RouteAction | WeatherAction | PoiSearchAction,
    Field(discriminator="tool"),
]


class ResearchPlan(BaseModel):
    """One bounded batch of evidence calls; no iterative discovery loop."""

    actions: list[ResearchAction] = Field(default_factory=list, max_length=_MAX_PLAN_ACTIONS)


class DraftVerificationResult(BaseModel):
    item_id: str
    summary: str
    source_urls: list[str] = Field(default_factory=list)
    tool_evidence: list[str] = Field(default_factory=list)
    status: Literal["verified", "conflicting", "unresolved"]


class DraftClaim(BaseModel):
    claim: str
    source_urls: list[str] = Field(default_factory=list)
    tool_evidence: list[str] = Field(default_factory=list)
    status: Literal["verified", "conflicting", "unresolved"]


class DraftSource(BaseModel):
    title: str
    url: str
    source_type: str | None = None


class ResearchFindingsDraft(BaseModel):
    """Lenient model output; Host enforces the real evidence contract afterward."""

    topic: str
    summary: str | None = None
    verification_results: list[DraftVerificationResult] = Field(default_factory=list)
    claims: list[DraftClaim] = Field(default_factory=list)
    sources: list[DraftSource] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class EvidencePacket(BaseModel):
    item_ids: list[str] = Field(default_factory=list)
    tool: str
    args: dict[str, Any]
    result: Any


def _valid_actions_for_request(
    request: ResearchRequest,
    actions: list[ResearchAction],
) -> list[ResearchAction]:
    """Keep only Planner actions bound to real request verification item ids.

    An action with an unknown or empty item_id is dropped without correction,
    fuzzy matching, checklist expansion, or a Planner re-request. The affected
    verification item then naturally falls back to ``unresolved`` because it has
    no executed evidence.
    """
    allowed_ids = {item.id for item in request.verification_items}
    return [
        action
        for action in actions
        if action.item_ids and all(item_id in allowed_ids for item_id in action.item_ids)
    ]


def _item_impact(request: ResearchRequest, item_id: str) -> str:
    """Return the impact level of the verification item owning ``item_id``.

    ``unknown`` is treated as ``high`` for budgeting so an undeclared item never
    silently escapes the strictest safety budget.
    """
    for item in request.verification_items:
        if item.id == item_id:
            return "high" if item.impact == "unknown" else item.impact
    return "high"


def _impact_budget() -> dict[str, int]:
    """Return the Research Task budget keyed by effective impact level."""
    budget = dict(settings.RESEARCH_AGENT_IMPACT_BUDGET)
    # unknown items must never exceed the strictest (high) budget.
    budget["unknown"] = budget.get("high", 5)
    return budget


def _cap_actions_by_impact(
    request: ResearchRequest,
    actions: list[ResearchAction],
) -> list[ResearchAction]:
    """Hard-cap planned actions by the number of distinct Research Tasks served.

    The budget unit is the Research Task (one verification item), NOT the raw tool
    call: one task may legitimately use several tools (POI + Maps + Web Search), so
    multiple actions for the SAME item all stay within that item's single slot.
    Only when an action would serve a NEW item whose impact level has already
    reached its cap is it dropped; the dropped item falls back to unresolved
    instead of over-spending.

    Default budgets: high/unknown <= 5 / medium <= 3 / low <= 0. ``low`` never
    consumes research budget (nice-to-have facts never block the Final Plan).
    """
    if not actions:
        return actions
    budget = _impact_budget()
    served: dict[str, str] = {}  # item_id -> effective impact level
    impact_counts: dict[str, int] = {}  # effective impact level -> served items
    kept: list[ResearchAction] = []
    for action in actions:
        impacted_ids = [
            item_id
            for item_id in action.item_ids
            if _item_impact(request, item_id) in {"high", "medium", "unknown"}
        ]
        if not impacted_ids:
            continue
        new_items = [item_id for item_id in impacted_ids if item_id not in served]
        over_budget = any(
            impact_counts.get(_item_impact(request, item_id), 0)
            >= budget.get(_item_impact(request, item_id), 0)
            for item_id in new_items
        )
        if over_budget:
            continue
        for item_id in impacted_ids:
            if item_id not in served:
                impact = _item_impact(request, item_id)
                served[item_id] = impact
                impact_counts[impact] = impact_counts.get(impact, 0) + 1
        kept.append(action)
    return kept


class ResearchBlockStatus(BaseModel):
    """Impact-aware resolution of one verification item's evidence state.

    ``impact`` mirrors the input item's declared level (unknown normalized to
    high). ``blocked`` is True when a high/unknown impact item could not be
    resolved and therefore threatens plan feasibility.
    """

    item_id: str
    impact: str
    status: Literal["verified", "conflicting", "unresolved"]
    blocked: bool = False
    warning: bool = False


def classify_research_results(
    request: ResearchRequest,
    findings: ResearchFindings,
) -> list[ResearchBlockStatus]:
    """Grade each verification result by its impact on the final decision.

    unresolved handling is impact-aware, NOT uniformly non-blocking:
    - high / unknown: unresolved blocks the plan (fallback or block).
    - medium: unresolved only warns (degrade gracefully, never fails the plan).
    - low: unresolved never blocks (nice-to-have).
    """
    result_by_id = {result.item_id: result for result in findings.verification_results}
    statuses: list[ResearchBlockStatus] = []
    for item in request.verification_items:
        impact = item.impact
        effective_impact = "high" if impact == "unknown" else impact
        result = result_by_id.get(item.id)
        status = result.status if result is not None else "unresolved"
        unresolved = status == "unresolved"
        blocked = unresolved and effective_impact == "high"
        warning = unresolved and effective_impact == "medium"
        statuses.append(
            ResearchBlockStatus(
                item_id=item.id,
                impact=effective_impact,
                status=status,
                blocked=blocked,
                warning=warning,
            )
        )
    return statuses


def evidence_sufficiency(
    request: ResearchRequest,
    findings: ResearchFindings,
) -> bool:
    """Return True when every high/unknown impact task is resolved.

    Stop-search gate evaluated PER Research Task, not per whole run: the research
    layer may keep exploring only while some high-impact task remains unresolved.
    Unresolved medium/low tasks never force additional searches.
    """
    return not any(
        status.blocked
        for status in classify_research_results(request, findings)
    )


def _item_evidence_scope(
    packets: list[EvidencePacket],
    item_id: str,
) -> tuple[set[str], set[str]]:
    """Return the URLs and dedicated tools this item is actually allowed to use.

    Only packets whose ``item_ids`` include ``item_id`` count as that item's
    evidence. Web URLs come from the observed search_web/web_fetch results of those
    packets; dedicated tool names come from the tool types of those packets. This
    replaces any global ``trace.web_urls`` / ``trace.successful_tools`` proof for a
    single ``VerificationResult``.
    """
    allowed_urls: set[str] = set()
    allowed_tools: set[str] = set()
    for packet in packets:
        if item_id not in packet.item_ids:
            continue
        if not _result_is_usable(packet.result):
            continue
        if packet.tool in {"search_web", "web_fetch"}:
            if not isinstance(packet.result, dict):
                continue
            if packet.tool == "search_web":
                rows = packet.result.get("results")
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    url = row.get("url")
                    if isinstance(url, str) and url.startswith(("http://", "https://")):
                        allowed_urls.add(url)
            else:
                url = packet.result.get("url")
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    allowed_urls.add(url)
        else:
            allowed_tools.add(packet.tool)
    return allowed_urls, allowed_tools


def _observed_source_catalog(packets: list[EvidencePacket]) -> dict[str, EvidenceSource]:
    catalog: dict[str, EvidenceSource] = {}
    for packet in packets:
        if not isinstance(packet.result, dict):
            continue
        if packet.tool == "search_web":
            rows = packet.result.get("results")
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                url = row.get("url")
                if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                    continue
                title = row.get("title")
                site_name = row.get("site_name")
                catalog[url] = EvidenceSource(
                    title=str(title or site_name or url),
                    url=url,
                    source_type=str(site_name) if site_name else None,
                )
        elif packet.tool == "web_fetch":
            url = packet.result.get("url")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                continue
            title = packet.result.get("title")
            catalog[url] = EvidenceSource(
                title=str(title or url),
                url=url,
                source_type="fetched source",
            )
    return catalog


def _draft_to_findings(
    request: ResearchRequest,
    draft: ResearchFindingsDraft,
    packets: list[EvidencePacket],
) -> ResearchFindings:
    """Apply deterministic evidence normalization before strict Host attestation."""

    source_catalog = _observed_source_catalog(packets)
    for source in draft.sources:
        if source.url not in source_catalog:
            continue
        observed = source_catalog[source.url]
        source_catalog[source.url] = EvidenceSource(
            title=source.title or observed.title,
            url=source.url,
            source_type=source.source_type or observed.source_type,
        )

    allowed_tools = set(get_args(EvidenceToolName))
    unresolved = list(dict.fromkeys(draft.unresolved))
    used_urls: set[str] = set()

    def normalize_evidence(
        *,
        source_urls: list[str],
        tool_evidence: list[str],
        status: Literal["verified", "conflicting", "unresolved"],
        marker: str,
        allowed_urls: set[str] | None = None,
        allowed_tool_names: set[str] | None = None,
    ) -> tuple[
        list[str],
        list[EvidenceToolName],
        Literal["verified", "conflicting", "unresolved"],
    ]:
        # Item-scoped normalization: a URL/tool is only acceptable for a
        # VerificationResult if it belongs to that item's own evidence packets.
        url_filter = allowed_urls if allowed_urls is not None else set(source_catalog)
        tool_filter = allowed_tool_names if allowed_tool_names is not None else allowed_tools
        urls = list(
            dict.fromkeys(
                url for url in source_urls if url in source_catalog and url in url_filter
            )
        )
        tools = cast(
            list[EvidenceToolName],
            list(dict.fromkeys(tool for tool in tool_evidence if tool in tool_filter)),
        )
        normalized_status = status
        if normalized_status in {"verified", "conflicting"} and not (urls or tools):
            normalized_status = "unresolved"
            if marker not in unresolved:
                unresolved.append(marker)
        used_urls.update(urls)
        return urls, tools, normalized_status

    draft_results = {result.item_id: result for result in draft.verification_results}
    results: list[VerificationResult] = []
    if request.verification_items:
        result_specs: list[tuple[str, DraftVerificationResult | None]] = [
            (item.id, draft_results.get(item.id)) for item in request.verification_items
        ]
    else:
        result_specs = [(result.item_id, result) for result in draft.verification_results]

    for item_id, result in result_specs:
        if result is None:
            results.append(
                VerificationResult(
                    item_id=item_id,
                    summary="当前研究未能可靠确认该核验项。",
                    status="unresolved",
                )
            )
            marker = f"Missing verification result: {item_id}"
            if marker not in unresolved:
                unresolved.append(marker)
            continue
        item_urls, item_tools = _item_evidence_scope(packets, item_id)
        urls, tools, status = normalize_evidence(
            source_urls=result.source_urls,
            tool_evidence=result.tool_evidence,
            status=result.status,
            marker=f"Draft evidence incomplete for verification item: {item_id}",
            allowed_urls=item_urls,
            allowed_tool_names=item_tools,
        )
        results.append(
            VerificationResult(
                item_id=item_id,
                summary=result.summary,
                source_urls=urls,
                tool_evidence=tools,
                status=status,
            )
        )

    claims: list[EvidenceClaim] = []
    for claim in draft.claims:
        urls, tools, status = normalize_evidence(
            source_urls=claim.source_urls,
            tool_evidence=claim.tool_evidence,
            status=claim.status,
            marker=f"Draft evidence incomplete for claim: {claim.claim}",
        )
        claims.append(
            EvidenceClaim(
                claim=claim.claim,
                source_urls=urls,
                tool_evidence=tools,
                status=status,
            )
        )

    sources = [source_catalog[url] for url in sorted(used_urls)]
    return ResearchFindings(
        topic=draft.topic or request.objective,
        summary=draft.summary,
        verification_results=results,
        claims=claims,
        sources=sources,
        media=[],
        unresolved=unresolved,
    )


_PLANNER_INSTRUCTIONS = """\
你是旅行研究查询规划器。你的唯一任务是为一个 ResearchRequest 生成最小、可并行执行的证据查询批次，不做最终回答。

规则：
- 每个 action 必须绑定至少一个 input verification_item：item_ids 必须逐字使用 request 中真实存在的 id，不允许为空，不允许创建 checklist 之外的 id；一个 action 只能服务它明确绑定的 items。
- actions 总数最多 4；默认每个 verification item 只安排 1 个 action，只有一条查询明显不足时才允许第 2 个。
- 每个 verification item 有 impact 分级（high/medium/low/unknown），它是该 Research Task 对最终决策的影响程度：high=方案不可执行或核心路线要改，medium=只影响体验质量，low=锦上添花，unknown=未分级按 high 处理。
- 遵守 impact 预算（按 Research Task 数量，不是 tool 数量）：high/unknown 最多 5 个、medium 最多 3 个、low 默认 0（不安排搜索）。超过预算的 item 直接不安排 action，返回 unresolved 即可。
- 同一 item 的多个 action 属于同一个 Research Task，可以同时保留（POI / Maps / Web 可共用于一个核验项）。
- 不为可以由已有外部事实直接推导的结论单独查询，例如安全余量、是否值得、最终取舍。
- 开放、预约、政策、当前价格等动态 Web 事实优先 search_web(authoritative=true)。
- 涉及铁路/班次/赶车风险的交通 item，必要时可安排两个互补 Web 查询：总体公共交通可达性 + 明确铁路/高铁/时刻/换乘。
- 两点路线和现实市内通勤时间可用 search_maps；天气只在 request 的决策真的依赖近期天气时用 get_weather。
- POI 名称、坐标、地址、评分、人均等结构化地点事实优先 search_poi，不要改用 Web 普查。
- 不要使用 time_range；需要日期范围时直接写进 query，避免工具参数表达差异。
- 不生成 web_fetch action；Host 会自动读取 authoritative search 的首个权威来源。
- 如果证据不足，Finalizer 可以返回 unresolved；不要通过增加查询追求“资料完整”。
只输出 ResearchPlan。
"""

def _runtime_clock_instructions() -> str:
    return runtime_clock_context()


_FINALIZER_INSTRUCTIONS = """\
你是旅行研究压缩器。你只能使用输入 evidence 中实际出现的事实、URL 和 dedicated tool result 生成 ResearchFindings；禁止继续搜索或补写模型记忆中的当前事实。

规则：
- 先直接回答 ResearchRequest.objective，再给最少的决策关键证据。
- 每个 input verification_item 必须且只能返回一条 verification_result；没有足够证据就 unresolved。
- Web verified/conflicting 事实的 source_urls 必须逐字使用 evidence 中实际出现的 URL。sources 可以只列你明确使用的来源；Host 会用实际 evidence 补全来源元数据并做最终 attestation。
- search_maps/get_weather/search_poi 等 dedicated tool 事实可使用对应 tool_evidence。
- 可以用已经核验的外部事实做算术、时间余量和可执行性推导；这种推导不需要额外搜索。
- 多种交通证据同时存在时，比较后优先现实、稳妥且总耗时更短的方案；具体未来班次无法可靠确认时明确 unresolved，不得编造。
- claims 只保留 summary 无法承载但会改变决策的少量事实，不要复制 verification_results。
- 不要因为漏写 sources、证据字段不完美而反复修正输出；不确定就标 unresolved，Host 会负责严格降级。
- 输出必须高度压缩；不要生成完整 itinerary。
只输出 ResearchFindings。
"""


def _fallback_findings(request: ResearchRequest) -> ResearchFindings:
    return ResearchFindings(
        topic=request.objective,
        verification_results=[
            VerificationResult(
                item_id=item.id,
                summary="当前研究主题暂时无法可靠完成。",
                status="unresolved",
            )
            for item in request.verification_items
        ],
        unresolved=["当前研究主题暂时无法可靠完成。"],
    )


def _trace_for_request(request: ResearchRequest) -> ResearchEvidenceTrace:
    return ResearchEvidenceTrace(
        topic_title=request.title,
        verification_items={
            item.id: {
                "id": item.id,
                "entity": item.entity,
                "aspect": item.aspect,
                "question": item.question,
            }
            for item in request.verification_items
        },
    )


def _model_responses(result: Any) -> tuple[ModelResponse, ...]:
    return tuple(
        message
        for message in result.new_messages()
        if isinstance(message, ModelResponse)
    )


def _progress_start(request: ResearchRequest) -> None:
    state = get_research_request_state()
    if state is None:
        return
    state.emit_progress(
        topic=request.objective[:160],
        status="started",
        stage="research",
        label="开始核验研究主题",
        topic_title=request.title,
        verification_items=[item.model_dump(mode="json") for item in request.verification_items]
        or None,
    )


def _progress_finish(request: ResearchRequest, findings: ResearchFindings, *, succeeded: bool) -> None:
    state = get_research_request_state()
    if state is None:
        return
    items = {item.id: item for item in request.verification_items}
    for result in findings.verification_results:
        item = items.get(result.item_id)
        if item is None:
            continue
        if result.status == "verified":
            label = f"已确认{item.entity}：{item.aspect}"
            status = "completed"
        elif result.status == "conflicting":
            label = f"来源存在冲突：{item.entity} · {item.aspect}"
            status = "unresolved"
        else:
            label = f"暂未可靠确认：{item.entity} · {item.aspect}"
            status = "unresolved"
        state.emit_progress(
            topic=request.objective[:160],
            status=status,
            stage="verification",
            label=label,
            topic_title=request.title,
            item_id=item.id,
            entity=item.entity,
            aspect=item.aspect,
            item_status=result.status,
            item_summary=result.summary,
        )
    state.emit_progress(
        topic=request.objective[:160],
        status="completed" if succeeded else "unresolved",
        stage="research",
        label="研究主题核验完成" if succeeded else "研究主题未能可靠完成",
        topic_title=request.title,
    )


async def _execute_action(action: ResearchAction) -> EvidencePacket:
    result: Any
    if isinstance(action, WebSearchAction):
        args: dict[str, Any] = {
            "query": action.query,
            "count": _WEB_RESULT_COUNT,
            "authoritative": action.authoritative,
        }
        result = await search_web(
            action.query,
            count=_WEB_RESULT_COUNT,
            authoritative=action.authoritative,
            max_snippet_length=_WEB_SNIPPET_LENGTH,
        )
    elif isinstance(action, RouteAction):
        args = {
            "origin": action.origin,
            "destination": action.destination,
            "mode": action.mode,
        }
        result = await search_maps(action.origin, action.destination, mode=action.mode)
    elif isinstance(action, WeatherAction):
        args = {"city": action.city, "forecast": action.forecast}
        result = await get_weather(action.city, forecast=action.forecast)
    else:
        args = {
            "keywords": action.keywords,
            "region": action.region,
            "strict_region": action.strict_region,
            "limit": 3,
        }
        result = await search_poi(
            action.keywords,
            region=action.region,
            strict_region=action.strict_region,
            limit=3,
        )
    return EvidencePacket(
        item_ids=action.item_ids,
        tool=action.tool,
        args=args,
        result=result,
    )


def _top_search_url(packet: EvidencePacket) -> str | None:
    if packet.tool != "search_web" or not packet.args.get("authoritative"):
        return None
    if not isinstance(packet.result, dict):
        return None
    rows = packet.result.get("results")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = row.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url
    return None


async def _fetch_authoritative(packet: EvidencePacket) -> EvidencePacket | None:
    url = _top_search_url(packet)
    if url is None:
        return None
    fetcher = WebFetchLocalTool(
        max_content_length=_FETCH_CONTENT_CHARS,
        allow_local_urls=False,
        timeout=15,
    )
    fetched: Any
    try:
        fetched = await bound_tool_execution(fetcher(url))
    except Exception as exc:
        fetched = {"error": f"来源读取失败：{type(exc).__name__}"}
    if (
        isinstance(fetched, dict)
        and isinstance(fetched.get("url"), str)
        and isinstance(fetched.get("content"), str)
    ):
        plain_result: Any = dict(fetched)
    else:
        plain_result = {"error": "来源不是可读取的文本页面"}
    return EvidencePacket(
        item_ids=packet.item_ids,
        tool="web_fetch",
        args={"url": url},
        result=plain_result,
    )


async def run_bounded_research(
    request: ResearchRequest,
    *,
    model: Model | KnownModelName | str | None,
) -> ResearchFindings:
    """Run one topic as a two-model-call context compressor."""

    if model is None:
        return _fallback_findings(request)

    _progress_start(request)
    trace = _trace_for_request(request)
    state = get_research_request_state()
    responses: list[ModelResponse] = []
    plan_usage = RunUsage()
    final_usage = RunUsage()
    plan_attempted = False
    final_attempted = False
    tool_calls = 0
    findings = _fallback_findings(request)
    succeeded = False

    planner = Agent(
        model,
        output_type=ResearchPlan,
        instructions=(_PLANNER_INSTRUCTIONS, _runtime_clock_instructions),
        model_settings=ModelSettings(
            timeout=settings.LITELLM_CLIENT_TIMEOUT_SECONDS,
            thinking=False,
        ),
        defer_model_check=True,
    )
    finalizer = Agent(
        model,
        output_type=ResearchFindingsDraft,
        instructions=(_FINALIZER_INSTRUCTIONS, _runtime_clock_instructions),
        model_settings=ModelSettings(
            timeout=settings.LITELLM_CLIENT_TIMEOUT_SECONDS,
            thinking=False,
        ),
        defer_model_check=True,
    )

    try:
        if settings.RESEARCH_AGENT_MODEL_REQUEST_LIMIT < 2:
            return findings

        plan_attempted = True
        plan_result = await planner.run(
            request.model_dump_json(exclude_none=True),
            usage=plan_usage,
        )
        responses.extend(_model_responses(plan_result))

        planned_actions = plan_result.output.actions[: _MAX_PLAN_ACTIONS]
        actions = _valid_actions_for_request(request, planned_actions)
        # Hard cap per impact budget: Research Task (distinct verification item)
        # count is limited, NOT raw tool calls. One task may use several tools
        # (POI + Maps + Web Search); actions serving an already-served item stay.
        # Actions that would introduce a new item at a saturated impact level are
        # dropped; that item falls back to unresolved instead of over-spending.
        actions = _cap_actions_by_impact(request, actions)
        packets = list(await asyncio.gather(*(_execute_action(action) for action in actions)))
        tool_calls += len(packets)
        for packet in packets:
            record_research_tool_observation(
                trace,
                tool_name=packet.tool,
                args=packet.args,
                result=packet.result,
            )

        # Authoritative-source fetch is part of the same Research Task, not a
        # separate tool budget: at most _MAX_AUTH_FETCHES authoritative pages are
        # read per child run as a fixed context-compression cost.
        authoritative_packets = [packet for packet in packets if _top_search_url(packet)]
        fetch_count = min(_MAX_AUTH_FETCHES, len(authoritative_packets))
        fetched = list(
            await asyncio.gather(
                *(_fetch_authoritative(packet) for packet in authoritative_packets[:fetch_count])
            )
        )
        fetch_packets = [packet for packet in fetched if packet is not None]
        tool_calls += len(fetch_packets)
        for packet in fetch_packets:
            record_research_tool_observation(
                trace,
                tool_name=packet.tool,
                args=packet.args,
                result=packet.result,
            )

        evidence_payload = {
            "request": request.model_dump(mode="json", exclude_none=True),
            "evidence": [
                packet.model_dump(mode="json") for packet in (*packets, *fetch_packets)
            ],
        }
        final_attempted = True
        final_result = await finalizer.run(
            json.dumps(evidence_payload, ensure_ascii=False, separators=(",", ":")),
            usage=final_usage,
        )
        responses.extend(_model_responses(final_result))
        strict_findings = _draft_to_findings(
            request,
            final_result.output,
            [*packets, *fetch_packets],
        )
        attested = attest_research_findings(strict_findings, trace)
        if isinstance(attested, ResearchFindings):
            findings = attested
            succeeded = True
        return findings
    except (ModelAPIError, UnexpectedModelBehavior):
        return findings
    finally:
        if state is not None:
            state.record_research_run(
                ResearchUsageObservation(
                    responses=tuple(responses),
                    requests=(
                        max(plan_usage.requests, int(plan_attempted))
                        + max(final_usage.requests, int(final_attempted))
                    ),
                    tool_calls=tool_calls,
                )
            )
        _progress_finish(request, findings, succeeded=succeeded)
