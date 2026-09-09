"""PydanticAI execution engine.

This module is the composition root for framework-specific wiring (model,
provider, Harness capabilities, agent construction) while Product Runtime talks
to it through a framework-neutral surface.

Streaming uses the official PydanticAI ``VercelAIAdapter`` (transform/encode) so
reasoning / tool / text / source parts are produced by the framework — the Product
layer does NOT hand-roll a second browser wire protocol.

Reference:
  - PydanticAI Vercel AI integration:
    https://pydantic.dev/docs/ai/integrations/ui/vercel-ai/
  - PydanticAI OpenAI-compatible models:
    https://pydantic.dev/docs/ai/models/openai/
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from time import perf_counter
from typing import Any, Literal, cast

from openai import APITimeoutError, AsyncOpenAI
from pydantic_ai import Agent, AgentRunResult, RunContext, Tool, UsageLimits
from pydantic_ai.capabilities import AgentCapability, Capability
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UsageLimitExceeded
from pydantic_ai.messages import (
    BaseToolCallPart,
    ModelRequest,
    ModelResponse,
    NativeToolCallPart,
    NativeToolReturnPart,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    ThinkingPart,
    ThinkingPartDelta,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.openai import OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.ui.vercel_ai import VercelAIAdapter, VercelAIEventStream
from pydantic_ai.ui.vercel_ai.request_types import SubmitMessage, TextUIPart, UIMessage

from app.agent.capabilities.travel import build_travel_capabilities
from app.agent.context.runtime_clock import runtime_clock_context
from app.agent.debug_logging import debug_runtime_log
from app.agent.executor import (
    AgentExecutionError,
    AgentExecutionErrorCode,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutor,
    AgentRunObservation,
    AgentStreamTerminalKind,
)
from app.agent.prompts import MAIN_AGENT_INSTRUCTIONS
from app.agent.responses_compat import CompatibleOpenAIResponsesModel
from app.agent.tools.web_search import web_search
from app.agent.usage import AgentModelCallUsage, AgentTokenUsage, AgentUsage
from app.core.config import settings
from app.infra.vercel_protocol import decode_event, encode_event

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _MainAgentRunDeps:
    """Per-request switches consumed by dynamic Main capabilities."""

    enable_web_search: bool


def _prepare_web_search_tool(
    ctx: RunContext[_MainAgentRunDeps],
    tool_definition: ToolDefinition,
) -> ToolDefinition | None:
    """Expose application-hosted Web Search only when this request enables it."""
    deps = ctx.deps
    if isinstance(deps, _MainAgentRunDeps) and deps.enable_web_search:
        return tool_definition
    return None


class _ProductVercelAIEventStream(VercelAIEventStream):
    async def on_error(self, error: Exception) -> AsyncIterator[Any]:
        logger.error(
            "vercel ai event stream failed: %s: %s",
            type(error).__name__,
            error,
        )
        async for chunk in super().on_error(error):
            yield chunk


class _ProductVercelAIAdapter(VercelAIAdapter[_MainAgentRunDeps, str]):
    def build_event_stream(self) -> VercelAIEventStream:
        return _ProductVercelAIEventStream(
            self.run_input,
            accept=self.accept,
            sdk_version=self.sdk_version,
            server_message_id=self.server_message_id,
        )


_MODEL_TIMEOUT_STATUS_CODES = frozenset({408, 504})

# Must stay paired with the exact ``ai`` / ``@ai-sdk/react`` versions in the
# frontend manifest and the protocol fixture in the backend test suite.
VERCEL_AI_SDK_VERSION: Literal[7] = 7
_URL_RE = re.compile(r"https?://[^\s<>\]\[\"']+")


def _runtime_clock_instructions() -> str:
    """Adapt the framework-neutral clock into per-run dynamic instructions."""
    return runtime_clock_context()


def _litellm_openai_base_url() -> str:
    """Return the OpenAI-compatible base URL of the LiteLLM gateway.

    ``LITELLM_BASE_URL`` is the gateway root (e.g. ``http://litellm:4000``); the
    OpenAI-compatible client appends the Responses endpoint path, so the path must
    end in ``/v1``.
    """
    base = settings.LITELLM_BASE_URL.rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


def _model_rpc_settings(
    *,
    enable_thinking: bool = True,
    enable_web_search: bool = False,
) -> OpenAIResponsesModelSettings:
    """Return per-request settings, including provider-native request controls.

    The model is addressed through a LiteLLM logical name, so PydanticAI cannot
    infer its thinking profile and silently drops the unified ``thinking`` field.
    Ark Responses accepts the native top-level ``thinking.type`` control through
    the OpenAI SDK's ``extra_body`` escape hatch.
    """
    model_settings = OpenAIResponsesModelSettings(
        timeout=settings.LITELLM_CLIENT_TIMEOUT_SECONDS,
        parallel_tool_calls=True,
        extra_body={
            "thinking": {
                "type": "enabled" if enable_thinking else "disabled",
            }
        },
    )
    # Kept in the call signature for existing request-setting callers. Search
    # availability is owned by the dynamic function capability, not model settings.
    del enable_web_search
    return model_settings


def _main_usage_limits() -> UsageLimits:
    """Return the independent hard budget for one Main Agent run."""
    return UsageLimits(
        request_limit=settings.MAIN_MODEL_REQUEST_LIMIT,
        tool_calls_limit=settings.MAIN_TOOL_CALL_LIMIT,
    )


def _caused_by_sdk_timeout(exc: BaseException) -> bool:
    """Detect the timeout type hidden behind PydanticAI's ModelAPIError."""
    pending: list[BaseException] = [exc]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        if isinstance(current, APITimeoutError):
            return True
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return False


def _product_safe_model_error(exc: ModelAPIError) -> AgentExecutionError:
    """Map framework/provider errors without copying unsafe exception details."""
    if isinstance(exc, ModelHTTPError):
        if exc.status_code in _MODEL_TIMEOUT_STATUS_CODES:
            return AgentExecutionError(code="MODEL_TIMEOUT", retryable=True)
        if exc.status_code == 429:
            return AgentExecutionError(code="MODEL_RATE_LIMITED", retryable=True)
        return AgentExecutionError(
            code="MODEL_UNAVAILABLE",
            retryable=exc.status_code >= 500,
        )
    if _caused_by_sdk_timeout(exc):
        return AgentExecutionError(code="MODEL_TIMEOUT", retryable=True)
    return AgentExecutionError(code="MODEL_UNAVAILABLE", retryable=True)


@lru_cache(maxsize=1)
def get_chat_agent() -> Agent[_MainAgentRunDeps, str]:
    """Return the configured PydanticAI chat :class:`Agent`.

    The model is routed through LiteLLM using its logical model name, so provider
    credentials/fallback stay on the gateway instead of leaking into Product code.
    ``defer_model_check`` keeps construction safe even when the gateway is not up.
    """
    client = AsyncOpenAI(
        base_url=_litellm_openai_base_url(),
        api_key=settings.LITELLM_SERVICE_KEY,
        max_retries=0,
    )
    model = CompatibleOpenAIResponsesModel(
        settings.LLM_LOGICAL_MODEL,
        provider=OpenAIProvider(openai_client=client),
    )
    capabilities = cast(
        Sequence[AgentCapability[_MainAgentRunDeps]],
        (
            *build_travel_capabilities(
                enable_planning_core=settings.TRAVEL_CORE_ENABLED,
            ),
            Capability[_MainAgentRunDeps](
                id="main-web-search",
                description=(
                    "Search the public web for current or externally verifiable "
                    "information, including general news and non-travel topics."
                ),
                tools=(
                    Tool[_MainAgentRunDeps](
                        web_search,
                        takes_ctx=False,
                        prepare=_prepare_web_search_tool,
                    ),
                ),
            ),
        ),
    )
    return Agent(
        model,
        deps_type=_MainAgentRunDeps,
        model_settings=_model_rpc_settings(),
        # Literal guidance remains a cache-stable prefix. The callable is resolved
        # at run time, so a cached Agent never freezes the process-start clock.
        instructions=(
            MAIN_AGENT_INSTRUCTIONS,
            _runtime_clock_instructions,
        ),
        capabilities=capabilities,
        defer_model_check=True,
    )


def _to_model_messages(
    request: AgentExecutionRequest,
) -> list[ModelRequest | ModelResponse]:
    """Project product history into PydanticAI message_history.

    ``history`` is server-authoritative and already excludes the current message;
    we map user/assistant rows into ModelRequest/ModelResponse. The current message
    is carried as the adapter run input (see ``stream_vercel_events``), not here.
    """
    history: list[ModelRequest | ModelResponse] = []
    for message in request.history:
        if message.role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(message.content)]))
        else:
            history.append(ModelResponse(parts=[TextPart(content=message.content)]))
    return history


def _to_agent_usage(
    result: AgentRunResult[Any],
    *,
    logical_model: str,
) -> AgentUsage:
    """Map Main Agent usage into the Product usage contract."""
    main_responses = tuple(
        message
        for message in result.new_messages()
        if isinstance(message, ModelResponse)
    )
    model_calls = tuple(
        _to_agent_model_call_usage(
            message,
            call_index=call_index,
            logical_model=logical_model,
        )
        for call_index, message in enumerate(main_responses)
    )

    main_unattributed = max(0, result.usage.requests - len(main_responses))

    return AgentUsage(
        model_calls=model_calls,
        tool_calls=result.usage.tool_calls,
        unattributed_model_requests=main_unattributed,
    )


def _to_run_observation(
    result: AgentRunResult[Any],
    *,
    request: AgentExecutionRequest,
    source_url_count: int,
    output: str,
    started_at: float,
) -> AgentRunObservation:
    """Create a bounded summary; raw prompts and tool payloads stay out of DB."""
    tool_names: list[str] = []
    for message in result.new_messages():
        for part in getattr(message, "parts", ()):
            if isinstance(part, BaseToolCallPart) and part.tool_name not in tool_names:
                tool_names.append(part.tool_name)
    context_chars = len(request.message) + sum(
        len(item.content) for item in request.history
    )
    return AgentRunObservation(
        context_chars=context_chars,
        output_chars=len(output),
        source_url_count=source_url_count,
        elapsed_ms=round((perf_counter() - started_at) * 1000),
        tool_names=tuple(tool_names),
    )


def _log_agent_run_metrics(
    *,
    run_id: str,
    usage: AgentUsage,
    source_url_count: int,
    started_at: float,
) -> None:
    logger.info(
        "agent_run_metrics run_id=%s model_requests=%d tool_calls=%d "
        "input_tokens=%s output_tokens=%s cache_read_tokens=%s total_tokens=%s "
        "source_url_count=%d elapsed_ms=%d",
        run_id,
        usage.model_requests,
        usage.tool_calls,
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_read_tokens,
        usage.total_tokens,
        source_url_count,
        round((perf_counter() - started_at) * 1000),
    )


def _log_agent_run_failure(
    *,
    run_id: str,
    error_code: AgentExecutionErrorCode,
    started_at: float,
) -> None:
    logger.warning(
        "agent_run_failed run_id=%s error_code=%s elapsed_ms=%d",
        run_id,
        error_code,
        round((perf_counter() - started_at) * 1000),
    )


def _to_reasoning_summary(result: AgentRunResult[Any]) -> str | None:
    """Collect textual reasoning for the public UI, excluding provider metadata."""
    summaries: list[str] = []
    for message in result.new_messages():
        if not isinstance(message, ModelResponse):
            continue
        for part in message.parts:
            if not isinstance(part, ThinkingPart):
                continue
            content = part.content.strip()
            if not content and part.provider_details:
                raw_content = part.provider_details.get("raw_content")
                if isinstance(raw_content, list):
                    content = "".join(str(item) for item in raw_content).strip()
            if content:
                summaries.append(content)
    summary = "\n\n".join(summaries).strip()
    return summary or None


def _public_reasoning_summary(
    result: AgentRunResult[Any],
    *,
    enable_thinking: bool,
) -> str | None:
    """Return reasoning only when the request explicitly enabled it."""
    if not enable_thinking:
        return None
    return _to_reasoning_summary(result)


def _raw_content_text(details: dict[str, Any] | None) -> str:
    """Join the raw chain-of-thought fragments stored by the Responses API."""
    if not details:
        return ""
    raw_content = details.get("raw_content")
    if not isinstance(raw_content, list):
        return ""
    return "".join(str(item) for item in raw_content)


def _urls_from_value(value: Any) -> set[str]:
    """Collect URLs from structured tool results without inspecting final prose."""
    if isinstance(value, str):
        return {match.rstrip(".,);") for match in _URL_RE.findall(value)}
    if isinstance(value, dict):
        urls: set[str] = set()
        for child in value.values():
            urls.update(_urls_from_value(child))
        return urls
    if isinstance(value, (list, tuple, set, frozenset)):
        urls: set[str] = set()
        for child in value:
            urls.update(_urls_from_value(child))
        return urls
    if hasattr(value, "model_dump"):
        return _urls_from_value(value.model_dump(mode="python"))
    for attribute in ("url", "href", "source_page_url"):
        candidate = getattr(value, attribute, None)
        if isinstance(candidate, str):
            return _urls_from_value(candidate)
    return set()


def _source_urls(result: AgentRunResult[Any]) -> tuple[str, ...]:
    """Return URLs observed in this run's tool call/return parts."""
    urls: set[str] = set()
    for message in result.new_messages():
        for part in getattr(message, "parts", ()):
            if isinstance(
                part, (NativeToolCallPart, NativeToolReturnPart, ToolReturnPart)
            ):
                value = getattr(part, "args", None)
                if value is None:
                    value = getattr(part, "content", None)
                urls.update(_urls_from_value(value))
            elif isinstance(part, TextPart):
                # Native Responses web search citations are attached to the
                # assistant text part when raw annotations are requested.
                urls.update(_urls_from_value(part.provider_details))
    return tuple(sorted(urls))


async def _project_raw_reasoning(
    events: AsyncIterator[Any],
) -> AsyncIterator[Any]:
    """Project DeepSeek's raw chain-of-thought into the live reasoning stream.

    DeepSeek (routed through LiteLLM's Responses API) streams its chain of thought
    as raw ``reasoning_text`` deltas, which PydanticAI keeps under
    ``ThinkingPart.provider_details["raw_content"]`` while leaving
    ``ThinkingPart.content`` empty. The Vercel AI adapter only emits live reasoning
    text from ``content`` / ``content_delta``, so without this projection the browser
    shows an empty thinking area until the turn finishes and the persisted summary is
    reloaded. We rewrite raw-only thinking parts so the accumulated CoT rides the
    public channel, preserving ``provider_details`` for provider round-trips.
    """
    raw_details_by_index: dict[int, dict[str, Any]] = {}

    async for event in events:
        if isinstance(event, PartStartEvent) and isinstance(event.part, ThinkingPart):
            part = event.part
            if not part.content:
                details = part.provider_details or {}
                if text := _raw_content_text(details):
                    raw_details_by_index[event.index] = details
                    yield replace(event, part=replace(part, content=text))
                    continue
        elif isinstance(event, PartDeltaEvent) and isinstance(
            event.delta, ThinkingPartDelta
        ):
            delta = event.delta
            if not delta.content_delta:
                details = delta.provider_details
                previous = raw_details_by_index.get(event.index, {})
                if callable(details):
                    resolved = details(previous)
                elif isinstance(details, dict):
                    resolved = {**previous, **details}
                else:
                    resolved = None
                if resolved is not None:
                    previous_text = _raw_content_text(previous)
                    increment = _raw_content_text(resolved)[len(previous_text) :]
                    raw_details_by_index[event.index] = resolved
                    if increment:
                        yield replace(
                            event,
                            delta=replace(
                                delta,
                                content_delta=increment,
                                provider_details=resolved,
                            ),
                        )
                        continue
        yield event


def _to_agent_model_call_usage(
    message: ModelResponse,
    *,
    call_index: int,
    logical_model: str,
) -> AgentModelCallUsage:
    """Normalize one response while preserving unknown token usage as ``None``."""
    usage = message.usage
    counters = (
        usage.input_tokens,
        usage.output_tokens,
        usage.cache_write_tokens,
        usage.cache_read_tokens,
        usage.input_audio_tokens,
        usage.cache_audio_read_tokens,
        usage.output_audio_tokens,
    )
    token_usage: AgentTokenUsage | None
    if any(counters):
        token_usage = AgentTokenUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            input_audio_tokens=usage.input_audio_tokens,
            cache_audio_read_tokens=usage.cache_audio_read_tokens,
            output_audio_tokens=usage.output_audio_tokens,
        )
    else:
        token_usage = None
    return AgentModelCallUsage(
        call_index=call_index,
        logical_model=logical_model,
        token_usage=token_usage,
        reported_model=message.model_name,
        provider_response_id=message.provider_response_id,
    )


class PydanticAIExecutor:
    """Non-streaming PydanticAI implementation of the AgentExecutor port."""

    def __init__(
        self,
        agent: Agent | None = None,
        *,
        logical_model: str | None = None,
    ) -> None:
        self._agent = agent or get_chat_agent()
        self._uses_configured_agent = agent is not None
        self._logical_model = logical_model or settings.LLM_LOGICAL_MODEL

    async def execute(
        self,
        request: AgentExecutionRequest,
    ) -> AgentExecutionResult:
        started_at = perf_counter()
        run_id = str(request.request_id)
        message_history = _to_model_messages(request)
        # #region agent log
        debug_runtime_log(
            hypothesis_id="H5",
            location="pydantic_executor.py:PydanticAIExecutor.execute.entry",
            message="non-streaming agent execution started",
            data={
                "request_id": str(request.request_id),
                "history_count": len(request.history),
            },
            run_id=run_id,
        )
        # #endregion agent log
        try:
            agent = self._agent if self._uses_configured_agent else get_chat_agent()
            result = await agent.run(
                request.message,
                message_history=message_history,
                run_id=run_id,
                deps=_MainAgentRunDeps(
                    enable_web_search=request.enable_web_search,
                ),
                model_settings=_model_rpc_settings(
                    enable_thinking=request.enable_thinking,
                    enable_web_search=request.enable_web_search,
                ),
                usage_limits=_main_usage_limits(),
            )
            # #region agent log
            debug_runtime_log(
                hypothesis_id="H5",
                location="pydantic_executor.py:PydanticAIExecutor.execute.after_run",
                message="non-streaming agent execution returned",
                data={
                    "output_type": type(result.output).__name__,
                    "main_requests": result.usage.requests,
                },
                run_id=run_id,
            )
            # #endregion agent log
        except AgentExecutionError as exc:
            _log_agent_run_failure(
                run_id=run_id,
                error_code=exc.code,
                started_at=started_at,
            )
            raise
        except TimeoutError as exc:
            _log_agent_run_failure(
                run_id=run_id,
                error_code="MODEL_TIMEOUT",
                started_at=started_at,
            )
            raise AgentExecutionError(
                code="MODEL_TIMEOUT",
                retryable=True,
            ) from exc
        except ModelAPIError as exc:
            product_error = _product_safe_model_error(exc)
            _log_agent_run_failure(
                run_id=run_id,
                error_code=product_error.code,
                started_at=started_at,
            )
            raise product_error from exc
        except UsageLimitExceeded as exc:
            _log_agent_run_failure(
                run_id=run_id,
                error_code="MODEL_CALL_LIMIT_REACHED",
                started_at=started_at,
            )
            raise AgentExecutionError(
                code="MODEL_CALL_LIMIT_REACHED",
                retryable=False,
            ) from exc
        except Exception as exc:
            # Provider/gateway errors must not leak raw details into Product layer.
            _log_agent_run_failure(
                run_id=run_id,
                error_code="MODEL_UNAVAILABLE",
                started_at=started_at,
            )
            raise AgentExecutionError(
                code="MODEL_UNAVAILABLE",
                retryable=True,
            ) from exc

        content = result.output
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Agent returned an empty final message")
        source_urls = _source_urls(result)
        usage = _to_agent_usage(result, logical_model=self._logical_model)
        observation = _to_run_observation(
            result,
            request=request,
            source_url_count=len(source_urls),
            output=content,
            started_at=started_at,
        )
        _log_agent_run_metrics(
            run_id=run_id,
            usage=usage,
            source_url_count=len(source_urls),
            started_at=started_at,
        )
        return AgentExecutionResult(
            content=content,
            reasoning_summary=_public_reasoning_summary(
                result,
                enable_thinking=request.enable_thinking,
            ),
            source_urls=source_urls,
            usage=usage,
            observation=observation,
        )


def get_agent_executor() -> AgentExecutor:
    """Return the configured PydanticAI executor (non-streaming).

    Kept framework-neutral: the returned object satisfies the AgentExecutor port
    defined in ``app.agent.executor``.
    """
    return PydanticAIExecutor()


async def stream_vercel_events(
    request: AgentExecutionRequest,
    *,
    on_complete: Callable[[AgentExecutionResult], Awaitable[None]] | None = None,
    on_terminal: Callable[[AgentStreamTerminalKind, str | None], Awaitable[str]]
    | None = None,
) -> AsyncIterator[str]:
    """Stream a chat turn as Vercel AI SDK data-stream SSE strings.

    Uses the official ``VercelAIAdapter`` to transform PydanticAI native events
    (reasoning / tool / text / source) into the Vercel wire protocol, so the Product
    layer never hand-rolls the browser protocol.

    ``on_complete`` (if given) is awaited when the agent run finishes — *before* the
    adapter emits its ``finish`` chunk — so the Product layer can COMMIT the durable
    assistant message there (terminal gate: finish never precedes Product COMMIT).
    """
    started_at = perf_counter()
    run_id = str(request.request_id)
    adapter = _ProductVercelAIAdapter(
        agent=get_chat_agent(),
        run_input=SubmitMessage(
            id=str(request.request_id),
            messages=[
                UIMessage(
                    id="current",
                    role="user",
                    parts=[TextUIPart(text=request.message)],
                )
            ],
        ),
        accept="text/event-stream",
        sdk_version=VERCEL_AI_SDK_VERSION,
        server_message_id=run_id,
    )

    message_history = _to_model_messages(request)
    stream_error_code: AgentExecutionErrorCode | None = None
    source_urls: tuple[str, ...] = ()
    native_event_count = 0

    async def _on_complete(result: AgentRunResult[Any]) -> None:
        nonlocal source_urls
        source_urls = _source_urls(result)
        usage = _to_agent_usage(
            result,
            logical_model=settings.LLM_LOGICAL_MODEL,
        )
        _log_agent_run_metrics(
            run_id=run_id,
            usage=usage,
            source_url_count=len(source_urls),
            started_at=started_at,
        )
        # #region agent log
        debug_runtime_log(
            hypothesis_id="H4",
            location="pydantic_executor.py:_on_complete",
            message="adapter received completed agent result",
            data={
                "output_type": type(result.output).__name__,
                "main_requests": result.usage.requests,
                "source_urls": len(source_urls),
            },
            run_id=run_id,
        )
        # #endregion agent log
        if on_complete is None:
            return
        output = result.output
        if isinstance(output, str) and output.strip():
            observation = _to_run_observation(
                result,
                request=request,
                source_url_count=len(source_urls),
                output=output,
                started_at=started_at,
            )
            await on_complete(
                AgentExecutionResult(
                    content=output,
                    reasoning_summary=_public_reasoning_summary(
                        result,
                        enable_thinking=request.enable_thinking,
                    ),
                    source_urls=source_urls,
                    usage=usage,
                    observation=observation,
                )
            )

    native_events = _project_raw_reasoning(
        adapter.run_stream_native(
            message_history=message_history,
            run_id=run_id,
            deps=_MainAgentRunDeps(
                enable_web_search=request.enable_web_search,
            ),
            model_settings=_model_rpc_settings(
                enable_thinking=request.enable_thinking,
                enable_web_search=request.enable_web_search,
            ),
            usage_limits=_main_usage_limits(),
        )
    )

    async def _classified_native_events() -> AsyncIterator[Any]:
        nonlocal stream_error_code, native_event_count
        # #region agent log
        debug_runtime_log(
            hypothesis_id="H4",
            location="pydantic_executor.py:_classified_native_events.entry",
            message="native stream execution started",
            data={"request_id": str(request.request_id)},
            run_id=run_id,
        )
        # #endregion agent log
        try:
            async for event in native_events:
                native_event_count += 1
                if native_event_count <= 8:
                    # #region agent log
                    debug_runtime_log(
                        hypothesis_id="H4",
                        location="pydantic_executor.py:_classified_native_events.event",
                        message="native stream event observed",
                        data={
                            "event_index": native_event_count,
                            "event_type": type(event).__name__,
                        },
                        run_id=str(request.request_id),
                    )
                    # #endregion agent log
                yield event
            # #region agent log
            debug_runtime_log(
                hypothesis_id="H4",
                location="pydantic_executor.py:_classified_native_events.exit",
                message="native stream execution exhausted",
                data={"event_count": native_event_count},
                run_id=str(request.request_id),
            )
            # #endregion agent log
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            stream_error_code = "MODEL_TIMEOUT"
            _log_agent_run_failure(
                run_id=run_id,
                error_code=stream_error_code,
                started_at=started_at,
            )
            # #region agent log
            debug_runtime_log(
                hypothesis_id="H5",
                location="pydantic_executor.py:_classified_native_events.timeout",
                message="native stream timed out",
                data={"event_count": native_event_count},
                run_id=run_id,
            )
            # #endregion agent log
            raise
        except ModelAPIError as exc:
            stream_error_code = _product_safe_model_error(exc).code
            _log_agent_run_failure(
                run_id=run_id,
                error_code=stream_error_code,
                started_at=started_at,
            )
            # #region agent log
            debug_runtime_log(
                hypothesis_id="H5",
                location="pydantic_executor.py:_classified_native_events.model_error",
                message="native stream model error",
                data={
                    "event_count": native_event_count,
                    "error_type": type(exc).__name__,
                },
                run_id=run_id,
            )
            # #endregion agent log
            raise
        except UsageLimitExceeded:
            stream_error_code = "MODEL_CALL_LIMIT_REACHED"
            _log_agent_run_failure(
                run_id=run_id,
                error_code=stream_error_code,
                started_at=started_at,
            )
            # #region agent log
            debug_runtime_log(
                hypothesis_id="H5",
                location="pydantic_executor.py:_classified_native_events.usage_error",
                message="native stream usage limit reached",
                data={"event_count": native_event_count},
                run_id=run_id,
            )
            # #endregion agent log
            raise

    events = adapter.transform_stream(
        _classified_native_events(),
        on_complete=_on_complete,
    )

    async for chunk in adapter.encode_stream(events):
        payload = decode_event(chunk)
        if (
            not request.enable_thinking
            and payload is not None
            and payload.get("type")
            in {"reasoning-start", "reasoning-delta", "reasoning-end"}
        ):
            continue
        if payload is not None and payload.get("type") == "finish":
            for url in source_urls:
                yield encode_event("source-url", sourceId=url, url=url)
        if on_terminal is not None and payload is not None:
            if payload.get("type") in {"abort", "error"}:
                kind = payload["type"]
                reason = stream_error_code if kind == "error" else payload.get("reason")
                replacement = await on_terminal(kind, reason)
                yield replacement
                continue
        yield chunk
