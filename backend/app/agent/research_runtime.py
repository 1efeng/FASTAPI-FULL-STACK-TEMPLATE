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

from pydantic import BaseModel
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ModelResponse,
    NativeToolCallPart,
    NativeToolReturnPart,
    ToolCallPart,
)
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
_DEDICATED_FACT_TOOLS = frozenset({"get_weather", "search_maps"})
_TOOL_PROGRESS_LABELS = {
    "web_search": "搜索当前来源",
    "web_fetch": "读取来源正文",
    "search_maps": "核验路线交通",
    "get_weather": "核验旅行日期天气",
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
    progress_queue: asyncio.Queue[dict[str, str]] = field(default_factory=asyncio.Queue)

    def record_research_run(self, observation: ResearchUsageObservation) -> None:
        # No await here: append is a tiny request-local critical section. Product
        # accounting totals remain exact for the request-local child execution.
        self.research_runs.append(observation)

    def emit_progress(self, *, topic: str, status: str, label: str) -> None:
        """Queue a safe product-facing milestone without exposing model reasoning."""
        self.progress_queue.put_nowait(
            {"topic": topic, "status": status, "label": label}
        )

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

    model_responses: list[ModelResponse] = field(default_factory=list)
    successful_tools: set[str] = field(default_factory=set)
    web_urls: set[str] = field(default_factory=set)
    image_assets: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)


_current_research_trace: ContextVar[ResearchEvidenceTrace | None] = ContextVar(
    "travel_agent_research_agent_trace",
    default=None,
)


def _research_topic(prompt: Any) -> str:
    """Extract only the bounded objective from a ResearchRequest prompt."""
    if isinstance(prompt, str):
        try:
            value = json.loads(prompt)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict) and isinstance(value.get("objective"), str):
            return value["objective"][:160]
    return "旅行事实核验"


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


def _extract_image_assets(value: Any) -> dict[tuple[str, str], dict[str, Any]]:
    """Index media rows returned inside provider-native search evidence."""

    assets: dict[tuple[str, str], dict[str, Any]] = {}
    for item in _iter_plain_values(value):
        if not isinstance(item, dict):
            continue
        image_url = item.get("image_url") or item.get("image")
        page_url = item.get("source_page_url") or item.get("url")
        if not (isinstance(image_url, str) and isinstance(page_url, str) and image_url and page_url):
            continue
        assets[(image_url, page_url)] = {
            "image_url": image_url,
            "source_page_url": page_url,
            "thumbnail_url": item.get("thumbnail_url") or item.get("thumbnail"),
            "title": item.get("title"),
            "width": item.get("width"),
            "height": item.get("height"),
            "source": item.get("source"),
        }
    return assets


def _record_native_search_response(
    response: ModelResponse,
    trace: ResearchEvidenceTrace,
) -> None:
    """Capture evidence returned by the provider-native web search tool."""

    for part in response.parts:
        if isinstance(part, NativeToolCallPart) and part.tool_name == "web_search":
            trace.web_urls.update(_extract_urls(part.args))
        elif isinstance(part, NativeToolReturnPart) and part.tool_name == "web_search":
            if part.outcome == "success":
                trace.successful_tools.add("web_search")
                trace.web_urls.update(_extract_urls(part.content))
                trace.image_assets.update(_extract_image_assets(part.content))


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


def _attest_findings(output: Any, trace: ResearchEvidenceTrace) -> Any:
    """Downgrade unsupported assertions using actual Research Agent tool evidence."""

    from app.agent.agents.research_agent import ResearchFindings

    if not isinstance(output, ResearchFindings):
        return output

    findings = output.model_copy(deep=True)
    findings.sources = [source for source in findings.sources if source.url in trace.web_urls]

    for claim in findings.claims:
        if claim.status != "verified":
            continue
        claim.source_urls = [url for url in claim.source_urls if url in trace.web_urls]
        claim.tool_evidence = [
            tool for tool in claim.tool_evidence if tool in trace.successful_tools
        ]
        if claim.source_urls or claim.tool_evidence:
            continue

        claim.status = "unresolved"
        marker = f"Host evidence validation failed for claim: {claim.claim}"
        if marker not in findings.unresolved:
            findings.unresolved.append(marker)

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


@dataclass
class ResearchAgentRuntimeCapability(AbstractCapability[object]):
    """Per-Research-Agent hooks for usage capture and evidence attestation."""

    @classmethod
    def get_serialization_name(cls) -> str | None:
        return None

    async def wrap_run(self, ctx: RunContext[object], *, handler: Any) -> Any:
        trace = ResearchEvidenceTrace()
        state = get_research_request_state()
        topic = _research_topic(ctx.prompt)
        if state is not None:
            state.emit_progress(topic=topic, status="started", label="开始核验研究主题")
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
                state.emit_progress(
                    topic=topic,
                    status="completed" if succeeded else "unresolved",
                    label=(
                        "研究主题核验完成"
                        if succeeded
                        else "研究主题未能可靠完成"
                    ),
                )
            _current_research_trace.reset(token)

    async def after_model_request(
        self,
        ctx: RunContext[object],
        *,
        request_context: Any,
        response: ModelResponse,
    ) -> ModelResponse:
        del ctx, request_context
        trace = _current_research_trace.get()
        if trace is not None:
            trace.model_responses.append(response)
            _record_native_search_response(response, trace)
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
            label = _TOOL_PROGRESS_LABELS.get(call.tool_name, "核验旅行事实")
            state.emit_progress(
                topic=_research_topic(ctx.prompt),
                status="checking",
                label=f"正在{label}",
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
            label = _TOOL_PROGRESS_LABELS.get(tool_name, "旅行事实")
            state.emit_progress(
                topic=_research_topic(ctx.prompt),
                status="checking" if usable else "unresolved",
                label=f"{label}{'已返回结果' if usable else '未能可靠返回'}",
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

        trace.successful_tools.add(tool_name)

        if tool_name == "web_fetch":
            # A successful official fetch attests the URL supplied to the actual tool.
            requested_url = args.get("url")
            if isinstance(requested_url, str) and requested_url.startswith(("http://", "https://")):
                trace.web_urls.add(requested_url)
            trace.web_urls.update(_extract_urls(result))
        elif tool_name in _DEDICATED_FACT_TOOLS:
            # Presence in ``successful_tools`` is sufficient for the dedicated
            # evidence token because the claim schema already restricts names.
            pass
        return result

    async def after_output_process(
        self,
        ctx: RunContext[object],
        *,
        output_context: Any,
        output: Any,
    ) -> Any:
        del ctx, output_context
        trace = _current_research_trace.get()
        return _attest_findings(output, trace) if trace is not None else output
