"""Request-scoped Research Agent accounting and evidence attestation.

Two invariants live here:

1. Research Agent budgets stay isolated from Main while Product accounting still
   receives every child model/tool call.
2. A Research Agent cannot self-certify evidence. ``verified`` claims and media
   survive only when the referenced evidence was observed from tools that actually
   executed in that Research Agent run.

The collector is intentionally request-scoped via ``ContextVar`` so concurrent
Product requests never share Research Agent state.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.tools import RunContext, ToolDefinition

from app.agent.debug_logging import debug_runtime_log

_URL_RE = re.compile(r"https?://[^\s<>\]\[\"']+")
_FAILURE_MARKERS = (
    "NO_RESULTS",
    "UNAVAILABLE",
    "TIMEOUT",
    "ERROR",
    "FAILED",
    "MISSING",
    "NOT_CONFIGURED",
    "失败",
    "暂时不可用",
    "未能",
    "无法",
    "缺少",
)
_DEDICATED_FACT_TOOLS = frozenset(
    {
        "search_poi",
        "get_poi_detail",
        "search_nearby",
        "get_weather",
        "search_maps",
    }
)
_TOOL_PROGRESS_STAGES = {
    "search_web": "web_search",
    "web_fetch": "web_fetch",
    "search_poi": "poi",
    "get_poi_detail": "poi",
    "search_nearby": "poi",
    "search_maps": "maps",
    "get_weather": "weather",
}


@dataclass(frozen=True, slots=True)
class ResearchUsageObservation:
    """One isolated Research Agent run as seen by Product accounting.

    ``responses`` preserves per-model-call token/provider evidence. ``requests`` can
    be larger than ``len(responses)`` if the framework counted a request for which no
    response object was available; Product then keeps that remainder unattributed
    instead of silently rewriting unknown usage as zero.
    """

    responses: tuple[ModelResponse, ...]
    requests: int
    tool_calls: int


@dataclass(slots=True)
class ResearchRequestState:
    """Mutable request-local collector for Research Agent child execution."""

    research_runs: list[ResearchUsageObservation] = field(default_factory=list)
    progress_queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)

    def record_research_run(self, observation: ResearchUsageObservation) -> None:
        # No await here: append is a tiny request-local critical section. Product
        # accounting totals remain exact for the request-local child execution.
        self.research_runs.append(observation)

    def emit_progress(
        self,
        *,
        topic: str,
        status: str,
        stage: str,
        label: str,
        **details: Any,
    ) -> None:
        """Queue a safe product-facing milestone without exposing model reasoning."""
        payload: dict[str, Any] = {
            "topic": topic,
            "status": status,
            "stage": stage,
            "label": label,
        }
        payload.update({key: value for key, value in details.items() if value is not None})
        self.progress_queue.put_nowait(payload)

    @property
    def research_requests(self) -> int:
        return sum(run.requests for run in self.research_runs)

    @property
    def research_tool_calls(self) -> int:
        return sum(run.tool_calls for run in self.research_runs)


_current_request_state: ContextVar[ResearchRequestState | None] = ContextVar(
    "travel_agent_research_request_state",
    default=None,
)


@contextmanager
def bind_research_request_state(state: ResearchRequestState) -> Iterator[ResearchRequestState]:
    """Bind one Product request's collector for Main and all inherited child tasks."""

    token = _current_request_state.set(state)
    try:
        yield state
    finally:
        _current_request_state.reset(token)


def get_research_request_state() -> ResearchRequestState | None:
    return _current_request_state.get()


@dataclass(slots=True)
class ResearchEvidenceTrace:
    """Actual execution evidence for exactly one Research Agent.run."""

    topic_title: str | None = None
    verification_items: dict[str, dict[str, str]] = field(default_factory=dict)
    model_responses: list[ModelResponse] = field(default_factory=list)
    successful_tools: set[str] = field(default_factory=set)
    web_urls: set[str] = field(default_factory=set)
    image_assets: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)


_current_research_trace: ContextVar[ResearchEvidenceTrace | None] = ContextVar(
    "travel_agent_research_agent_trace",
    default=None,
)


def _research_request_payload(prompt: Any) -> dict[str, Any] | None:
    if not isinstance(prompt, str):
        return None
    try:
        value = json.loads(prompt)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _research_topic(prompt: Any) -> str:
    """Extract only the bounded objective from a ResearchRequest prompt."""
    value = _research_request_payload(prompt)
    objective = value.get("objective") if value is not None else None
    if isinstance(objective, str):
        return objective[:160]
    return "旅行事实核验"


def _research_title(prompt: Any) -> str | None:
    value = _research_request_payload(prompt)
    if value is None:
        return None
    title = value.get("title")
    if not isinstance(title, str):
        return None
    normalized = " ".join(title.split())
    return normalized[:80] or None


def _verification_item_snapshots(prompt: Any) -> list[dict[str, str]]:
    value = _research_request_payload(prompt)
    raw_items = value.get("verification_items") if value is not None else None
    if not isinstance(raw_items, list):
        return []

    snapshots: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        item_id = raw_item.get("id")
        entity = raw_item.get("entity")
        aspect = raw_item.get("aspect")
        question = raw_item.get("question")
        if not all(isinstance(value, str) and value for value in (item_id, entity, aspect, question)):
            continue
        assert isinstance(item_id, str)
        assert isinstance(entity, str)
        assert isinstance(aspect, str)
        assert isinstance(question, str)
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        snapshots.append(
            {
                "id": item_id,
                "entity": entity,
                "aspect": aspect,
                "question": question,
                "status": "pending",
            }
        )
    return snapshots


def _topic_focus(topic: str) -> str:
    """Summarize user-visible verification dimensions from the research objective."""
    rules = (
        ("开放/闭馆", ("开放", "闭馆", "开园", "闭园", "营业")),
        ("预约/放票", ("预约", "放票", "预约渠道")),
        ("票价", ("门票", "票价", "价格", "费用")),
        ("交通", ("交通", "高铁", "公交", "地铁", "班次", "往返")),
        ("耗时", ("耗时", "时长", "到达", "返程")),
        ("天气", ("天气", "降雨", "气温")),
    )
    matched = [label for label, keywords in rules if any(keyword in topic for keyword in keywords)]
    return "、".join(matched[:5]) or "关键执行条件"


def _short_progress_value(value: Any, *, max_length: int = 36) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    return normalized if len(normalized) <= max_length else f"{normalized[: max_length - 1]}…"


def _source_domain(url: Any) -> str | None:
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    host = urlparse(url).hostname
    if not host:
        return None
    return host.removeprefix("www.")


def _tool_progress_label(
    tool_name: str,
    args: dict[str, Any],
    *,
    completed: bool,
    usable: bool = True,
) -> str:
    """Describe observable tool work without exposing raw model search queries."""
    if tool_name == "search_web":
        if not completed:
            return "正在检索最新来源"
        return "最新来源已检索" if usable else "联网检索失败"

    if tool_name == "web_fetch":
        domain = _source_domain(args.get("url"))
        target = f"：{domain}" if domain else ""
        if not completed:
            return f"正在读取来源{target}"
        return f"来源{'已读取' if usable else '读取失败'}{target}"

    if tool_name == "search_poi":
        keywords = _short_progress_value(args.get("keywords"))
        target = f"：{keywords}" if keywords else ""
        if not completed:
            return f"正在查找地点{target}"
        return f"地点{'已找到' if usable else '查询失败'}{target}"

    if tool_name == "get_poi_detail":
        if not completed:
            return "正在读取地点详情"
        return "地点详情已读取" if usable else "地点详情查询失败"

    if tool_name == "search_nearby":
        keywords = _short_progress_value(args.get("keywords"))
        target = f"：{keywords}" if keywords else ""
        if not completed:
            return f"正在查找附近地点{target}"
        return f"附近地点{'已找到' if usable else '查询失败'}{target}"

    if tool_name == "search_maps":
        origin = _short_progress_value(args.get("origin"))
        destination = _short_progress_value(args.get("destination"))
        route = f"：{origin} → {destination}" if origin and destination else ""
        if not completed:
            return f"正在核验路线{route}"
        return f"路线{'已核验' if usable else '核验失败'}{route}"

    if tool_name == "get_weather":
        city = _short_progress_value(args.get("city"))
        target = f"：{city}" if city else ""
        if not completed:
            return f"正在核验天气{target}"
        return f"天气{'已核验' if usable else '核验失败'}{target}"

    if not completed:
        return "正在核验旅行事实"
    return "旅行事实已核验" if usable else "旅行事实未能可靠核验"


def _iter_plain_values(value: Any) -> Iterator[Any]:
    """Walk common Pydantic/tool result containers without vendor-specific coupling."""

    if isinstance(value, BaseModel):
        yield from _iter_plain_values(value.model_dump(mode="python"))
        return
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_plain_values(child)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for child in value:
            yield from _iter_plain_values(child)
        return

    # ToolReturn and SourceUrlChunk are intentionally handled by public-looking
    # attributes so this remains compatible with the PydanticAI 2.28 result types.
    yielded_attr = False
    for attr in ("return_value", "metadata"):
        if hasattr(value, attr):
            yielded_attr = True
            yield from _iter_plain_values(getattr(value, attr))
    if hasattr(value, "url"):
        yielded_attr = True
        yield {"url": value.url}
    if not yielded_attr:
        yield value


def _extract_urls(value: Any) -> set[str]:
    urls: set[str] = set()
    for item in _iter_plain_values(value):
        if isinstance(item, dict):
            for key in ("url", "href", "source_page_url"):
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                    urls.add(candidate.rstrip(".,);"))
        elif isinstance(item, str):
            urls.update(match.rstrip(".,);") for match in _URL_RE.findall(item))
    return urls


def _result_is_usable(result: Any) -> bool:
    if isinstance(result, str):
        upper = result.upper()
        return not any(marker in upper for marker in _FAILURE_MARKERS)
    if isinstance(result, dict):
        if result.get("error"):
            return False
        status = result.get("status")
        if isinstance(status, str) and any(marker in status.upper() for marker in _FAILURE_MARKERS):
            return False
    return True


def record_research_tool_observation(
    trace: ResearchEvidenceTrace,
    *,
    tool_name: str,
    args: dict[str, Any],
    result: Any,
) -> bool:
    """Record one Host-executed research tool result into the evidence trace."""

    usable = _result_is_usable(result)
    if not usable:
        return False

    trace.successful_tools.add(tool_name)
    if tool_name == "search_web":
        trace.web_urls.update(_extract_urls(result))
    elif tool_name == "web_fetch":
        requested_url = args.get("url")
        if isinstance(requested_url, str) and requested_url.startswith(("http://", "https://")):
            trace.web_urls.add(requested_url)
        trace.web_urls.update(_extract_urls(result))
    return True


def _attest_findings(output: Any, trace: ResearchEvidenceTrace) -> Any:
    """Downgrade unsupported assertions using actual Research Agent tool evidence."""

    from app.agent.agents.research_agent import ResearchFindings, VerificationResult

    if not isinstance(output, ResearchFindings):
        return output

    findings = output.model_copy(deep=True)
    findings.sources = [source for source in findings.sources if source.url in trace.web_urls]

    for claim in findings.claims:
        claim.source_urls = [url for url in claim.source_urls if url in trace.web_urls]
        claim.tool_evidence = [
            tool for tool in claim.tool_evidence if tool in trace.successful_tools
        ]
        if claim.status not in {"verified", "conflicting"}:
            continue
        if claim.source_urls or claim.tool_evidence:
            continue

        claim.status = "unresolved"
        marker = f"Host evidence validation failed for claim: {claim.claim}"
        if marker not in findings.unresolved:
            findings.unresolved.append(marker)

    allowed_item_ids = set(trace.verification_items)
    result_by_id: dict[str, VerificationResult] = {}
    for result in findings.verification_results:
        if allowed_item_ids and result.item_id not in allowed_item_ids:
            marker = f"Unexpected verification result dropped: {result.item_id}"
            if marker not in findings.unresolved:
                findings.unresolved.append(marker)
            continue

        result.source_urls = [url for url in result.source_urls if url in trace.web_urls]
        result.tool_evidence = [
            tool for tool in result.tool_evidence if tool in trace.successful_tools
        ]
        if result.status in {"verified", "conflicting"} and not (
            result.source_urls or result.tool_evidence
        ):
            result.status = "unresolved"
            result.summary = "当前研究结果缺少可验证的执行证据。"
            marker = f"Host evidence validation failed for verification item: {result.item_id}"
            if marker not in findings.unresolved:
                findings.unresolved.append(marker)
        result_by_id[result.item_id] = result

    if trace.verification_items:
        findings.verification_results = []
        for item_id in trace.verification_items:
            item_result = result_by_id.get(item_id)
            if item_result is None:
                item_result = VerificationResult(
                    item_id=item_id,
                    summary="当前研究未能可靠确认该核验项。",
                    status="unresolved",
                )
                marker = f"Missing verification result: {item_id}"
                if marker not in findings.unresolved:
                    findings.unresolved.append(marker)
            findings.verification_results.append(item_result)
    else:
        findings.verification_results = list(result_by_id.values())

    # Media discovery has its own attestation lane. Image URLs are presentation
    # candidates only and can never migrate into ``web_urls`` fact evidence.
    filtered_media = []
    for asset in findings.media:
        observed = trace.image_assets.get((asset.image_url, asset.source_page_url))
        if observed is None:
            marker = f"Unattested image candidate dropped: {asset.place_name}"
            if marker not in findings.unresolved:
                findings.unresolved.append(marker)
            continue

        # Preserve the model's semantic place_name, but overwrite transport/media
        # metadata with the values returned by the provider-native search evidence.
        asset.image_url = str(observed["image_url"])
        asset.source_page_url = str(observed["source_page_url"])
        asset.thumbnail_url = (
            str(observed["thumbnail_url"]) if observed.get("thumbnail_url") else None
        )
        asset.title = str(observed["title"]) if observed.get("title") else None
        asset.width = int(observed["width"]) if observed.get("width") is not None else None
        asset.height = int(observed["height"]) if observed.get("height") is not None else None
        asset.source = str(observed["source"]) if observed.get("source") else None
        filtered_media.append(asset)
    findings.media = filtered_media
    return findings


def attest_research_findings(output: Any, trace: ResearchEvidenceTrace) -> Any:
    """Public package helper used by bounded and iterative research runtimes."""

    return _attest_findings(output, trace)


@dataclass
class ResearchAgentRuntimeCapability(AbstractCapability[object]):
    """Per-Research-Agent hooks for usage capture and evidence attestation."""

    @classmethod
    def get_serialization_name(cls) -> str | None:
        return None

    async def wrap_run(self, ctx: RunContext[object], *, handler: Any) -> Any:
        verification_items = _verification_item_snapshots(ctx.prompt)
        trace = ResearchEvidenceTrace(
            topic_title=_research_title(ctx.prompt),
            verification_items={item["id"]: item for item in verification_items},
        )
        state = get_research_request_state()
        topic = _research_topic(ctx.prompt)
        if state is not None:
            state.emit_progress(
                topic=topic,
                status="started",
                stage="research",
                label="开始核验研究主题",
                topic_title=trace.topic_title,
                verification_items=verification_items or None,
            )
        token = _current_research_trace.set(trace)
        succeeded = False
        # #region agent log
        debug_runtime_log(
            hypothesis_id="H2",
            location="research_runtime.py:wrap_run.entry",
            message="research agent started",
            data={"research_trace_created": True},
        )
        # #endregion agent log
        try:
            result = await handler()
            succeeded = True
            return result
        finally:
            # #region agent log
            debug_runtime_log(
                hypothesis_id="H2",
                location="research_runtime.py:wrap_run.exit",
                message="research agent finished",
                data={
                    "model_responses": len(trace.model_responses),
                    "successful_tools": sorted(trace.successful_tools),
                    "requests": ctx.usage.requests,
                    "tool_calls": ctx.usage.tool_calls,
                },
            )
            # #endregion agent log
            if state is not None:
                state.record_research_run(
                    ResearchUsageObservation(
                        responses=tuple(trace.model_responses),
                        requests=ctx.usage.requests,
                        tool_calls=ctx.usage.tool_calls,
                    )
                )
                if not succeeded:
                    for item in trace.verification_items.values():
                        state.emit_progress(
                            topic=topic,
                            status="unresolved",
                            stage="verification",
                            label=f"暂未可靠确认：{item['entity']} · {item['aspect']}",
                            topic_title=trace.topic_title,
                            item_id=item["id"],
                            entity=item["entity"],
                            aspect=item["aspect"],
                            item_status="unresolved",
                            item_summary="当前研究主题未能可靠完成。",
                        )
                state.emit_progress(
                    topic=topic,
                    status="completed" if succeeded else "unresolved",
                    stage="research",
                    label=(
                        "研究主题核验完成"
                        if succeeded
                        else "研究主题未能可靠完成"
                    ),
                    topic_title=trace.topic_title,
                )
            _current_research_trace.reset(token)

    async def before_model_request(
        self,
        ctx: RunContext[object],
        request_context: Any,
    ) -> Any:
        state = get_research_request_state()
        if state is not None:
            trace = _current_research_trace.get()
            topic = _research_topic(ctx.prompt)
            focus = _topic_focus(topic)
            state.emit_progress(
                topic=topic,
                status="checking",
                stage="analysis",
                label=(
                    f"正在拆分核验项：{focus}"
                    if trace is None or not trace.model_responses
                    else f"正在对照已获取证据：{focus}"
                ),
            )
        return request_context

    async def after_model_request(
        self,
        ctx: RunContext[object],
        *,
        request_context: Any,
        response: ModelResponse,
    ) -> ModelResponse:
        del request_context
        trace = _current_research_trace.get()
        if trace is not None:
            trace.model_responses.append(response)
        return response

    async def before_tool_execute(
        self,
        ctx: RunContext[object],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        del tool_def
        state = get_research_request_state()
        if state is not None:
            state.emit_progress(
                topic=_research_topic(ctx.prompt),
                status="checking",
                stage=_TOOL_PROGRESS_STAGES.get(call.tool_name, "tool"),
                label=_tool_progress_label(
                    call.tool_name,
                    args,
                    completed=False,
                ),
            )
        # #region agent log
        debug_runtime_log(
            hypothesis_id="H3",
            location="research_runtime.py:before_tool_execute",
            message="research agent tool started",
            data={"tool": call.tool_name},
        )
        # #endregion agent log
        return args

    async def after_tool_execute(
        self,
        ctx: RunContext[object],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        result: Any,
    ) -> Any:
        del tool_def
        trace = _current_research_trace.get()
        tool_name = call.tool_name
        usable = _result_is_usable(result)
        state = get_research_request_state()
        if state is not None:
            state.emit_progress(
                topic=_research_topic(ctx.prompt),
                status="checking" if usable else "unresolved",
                stage=_TOOL_PROGRESS_STAGES.get(tool_name, "tool"),
                label=_tool_progress_label(
                    tool_name,
                    args,
                    completed=True,
                    usable=usable,
                ),
            )
        # #region agent log
        debug_runtime_log(
            hypothesis_id="H3",
            location="research_runtime.py:after_tool_execute",
            message="research agent tool finished",
            data={"tool": tool_name, "usable": usable},
        )
        # #endregion agent log
        if trace is None or not usable:
            return result

        record_research_tool_observation(
            trace,
            tool_name=tool_name,
            args=args,
            result=result,
        )
        return result

    async def after_output_process(
        self,
        ctx: RunContext[object],
        *,
        output_context: Any,
        output: Any,
    ) -> Any:
        del output_context
        trace = _current_research_trace.get()
        if trace is None:
            return output

        attested = attest_research_findings(output, trace)
        if trace.verification_items:
            from app.agent.agents.research_agent import ResearchFindings

            state = get_research_request_state()
            if state is not None and isinstance(attested, ResearchFindings):
                topic = _research_topic(ctx.prompt)
                for result in attested.verification_results:
                    item = trace.verification_items.get(result.item_id)
                    if item is None:
                        continue
                    if result.status == "verified":
                        label = f"已确认{item['entity']}：{item['aspect']}"
                        progress_status = "completed"
                    elif result.status == "conflicting":
                        label = f"来源存在冲突：{item['entity']} · {item['aspect']}"
                        progress_status = "unresolved"
                    else:
                        label = f"暂未可靠确认：{item['entity']} · {item['aspect']}"
                        progress_status = "unresolved"
                    state.emit_progress(
                        topic=topic,
                        status=progress_status,
                        stage="verification",
                        label=label,
                        topic_title=trace.topic_title,
                        item_id=item["id"],
                        entity=item["entity"],
                        aspect=item["aspect"],
                        item_status=result.status,
                        item_summary=result.summary,
                    )
        return attested
