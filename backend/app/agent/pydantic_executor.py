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
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from functools import lru_cache
from typing import Any, Literal

from openai import APITimeoutError, AsyncOpenAI
from pydantic_ai import Agent, AgentRunResult, UsageLimits
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UsageLimitExceeded
from pydantic_ai.messages import (
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
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
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
    AgentStreamTerminalKind,
)
from app.agent.prompts import MAIN_TRAVEL_INSTRUCTIONS
from app.agent.research_runtime import (
    ResearchRequestState,
    bind_research_request_state,
)
from app.agent.usage import AgentModelCallUsage, AgentTokenUsage, AgentUsage
from app.core.config import settings
from app.infra.vercel_protocol import decode_event, encode_event

_GENERIC_CHAT_INSTRUCTIONS = (
    "你是「行伴」，一位专业的旅行规划助手。"
    "用用户使用的语言简洁、准确地回答问题；不编造实时信息。"
    "对于问候和简单问题直接简短回答，不展开冗长推理。"
    "如果公开 reasoning，必须使用用户的语言；中文用户使用简洁自然的中文，不输出英文思考片段。"
    "隐藏工具、搜索、模型和框架的内部执行细节，不向用户复述工具名、参数、"
    "原始查询、provider、重试或内部错误；只输出自然语言的结果、必要的不确定性和来源。"
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


def _model_rpc_settings(*, enable_thinking: bool = True) -> ModelSettings:
    """Return the timeout applied independently to every model request."""
    return ModelSettings(
        timeout=settings.LITELLM_CLIENT_TIMEOUT_SECONDS,
        thinking=True if enable_thinking else False,
    )


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


@lru_cache(maxsize=2)
def get_chat_agent(enable_web_search: bool = True) -> Agent:
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
    model = OpenAIResponsesModel(
        settings.LLM_LOGICAL_MODEL,
        provider=OpenAIProvider(openai_client=client),
    )
    return Agent(
        model,
        model_settings=_model_rpc_settings(),
        # Literal guidance remains a cache-stable prefix. The callable is resolved
        # at run time, so a cached Agent never freezes the process-start clock.
        instructions=(
            MAIN_TRAVEL_INSTRUCTIONS
            if settings.TRAVEL_CORE_ENABLED
            else _GENERIC_CHAT_INSTRUCTIONS,
            _runtime_clock_instructions,
        ),
        capabilities=build_travel_capabilities(
            enable_planning_core=settings.TRAVEL_CORE_ENABLED,
            enable_web_search=enable_web_search,
            research_model=model,
        ),
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
    research_state: ResearchRequestState | None = None,
) -> AgentUsage:
    """Map Main + optional Research Agent usage into one Product contract.

    Research Agent budgets stay role-local. Child responses are captured by
    request-scoped PydanticAI hooks and merged here explicitly so Product billing,
    quota analysis, and observability still see the complete request tree.
    """
    main_responses = tuple(
        message
        for message in result.new_messages()
        if isinstance(message, ModelResponse)
    )
    research_runs = (
        tuple(research_state.research_runs) if research_state is not None else ()
    )
    all_responses = (
        *main_responses,
        *(response for run in research_runs for response in run.responses),
    )
    model_calls = tuple(
        _to_agent_model_call_usage(
            message,
            call_index=call_index,
            logical_model=logical_model,
        )
        for call_index, message in enumerate(all_responses)
    )

    main_unattributed = max(0, result.usage.requests - len(main_responses))
    research_requests = sum(run.requests for run in research_runs)
    research_attributed = sum(len(run.responses) for run in research_runs)
    research_unattributed = max(0, research_requests - research_attributed)
    research_tool_calls = sum(run.tool_calls for run in research_runs)

    return AgentUsage(
        model_calls=model_calls,
        tool_calls=result.usage.tool_calls + research_tool_calls,
        unattributed_model_requests=main_unattributed + research_unattributed,
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
        return {
            match.rstrip(".,);")
            for match in _URL_RE.findall(value)
        }
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
            if isinstance(part, (NativeToolCallPart, NativeToolReturnPart, ToolReturnPart)):
                value = getattr(part, "args", None)
                if value is None:
                    value = getattr(part, "content", None)
                urls.update(_urls_from_value(value))
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
                    increment = _raw_content_text(resolved)[len(previous_text):]
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
        message_history = _to_model_messages(request)
        research_state = ResearchRequestState()
        # #region agent log
        debug_runtime_log(
            hypothesis_id="H5",
            location="pydantic_executor.py:PydanticAIExecutor.execute.entry",
            message="non-streaming agent execution started",
            data={"request_id": str(request.request_id), "history_count": len(request.history)},
            run_id=str(request.request_id),
        )
        # #endregion agent log
        try:
            agent = (
                self._agent
                if self._uses_configured_agent
                else get_chat_agent(request.enable_web_search)
            )
            with bind_research_request_state(research_state):
                result = await agent.run(
                    request.message,
                    message_history=message_history,
                    run_id=str(request.request_id),
                    model_settings=_model_rpc_settings(
                        enable_thinking=request.enable_thinking,
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
                    "research_runs": len(research_state.research_runs),
                },
                run_id=str(request.request_id),
            )
            # #endregion agent log
        except AgentExecutionError:
            raise
        except TimeoutError as exc:
            raise AgentExecutionError(
                code="MODEL_TIMEOUT",
                retryable=True,
            ) from exc
        except ModelAPIError as exc:
            raise _product_safe_model_error(exc) from exc
        except UsageLimitExceeded as exc:
            raise AgentExecutionError(
                code="MODEL_CALL_LIMIT_REACHED",
                retryable=False,
            ) from exc
        except Exception as exc:
            # Provider/gateway errors must not leak raw details into Product layer.
            raise AgentExecutionError(
                code="MODEL_UNAVAILABLE",
                retryable=True,
            ) from exc

        content = result.output
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Agent returned an empty final message")
        return AgentExecutionResult(
            content=content,
            reasoning_summary=_to_reasoning_summary(result),
            source_urls=_source_urls(result),
            usage=_to_agent_usage(
                result,
                    logical_model=self._logical_model,
                research_state=research_state,
            ),
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
    adapter = VercelAIAdapter(
        agent=get_chat_agent(request.enable_web_search),
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
        server_message_id=str(request.request_id),
    )

    message_history = _to_model_messages(request)
    stream_error_code: AgentExecutionErrorCode | None = None
    research_state = ResearchRequestState()
    source_urls: tuple[str, ...] = ()
    native_event_count = 0

    async def _on_complete(result: AgentRunResult[Any]) -> None:
        nonlocal source_urls
        source_urls = _source_urls(result)
        # #region agent log
        debug_runtime_log(
            hypothesis_id="H4",
            location="pydantic_executor.py:_on_complete",
            message="adapter received completed agent result",
            data={
                "output_type": type(result.output).__name__,
                "main_requests": result.usage.requests,
                "research_runs": len(research_state.research_runs),
                "source_urls": len(source_urls),
            },
            run_id=str(request.request_id),
        )
        # #endregion agent log
        if on_complete is None:
            return
        output = result.output
        if isinstance(output, str) and output.strip():
            await on_complete(
                AgentExecutionResult(
                    content=output,
                    reasoning_summary=_to_reasoning_summary(result),
                    source_urls=source_urls,
                    usage=_to_agent_usage(
                        result,
                        logical_model=settings.LLM_LOGICAL_MODEL,
                        research_state=research_state,
                    ),
                )
            )

    native_events = _project_raw_reasoning(
        adapter.run_stream_native(
            message_history=message_history,
            run_id=str(request.request_id),
            model_settings=_model_rpc_settings(
                enable_thinking=request.enable_thinking,
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
            run_id=str(request.request_id),
        )
        # #endregion agent log
        # Bind while the native run is actually driven. asyncio child tasks spawned
        # by inline Research Agent execution inherit this ContextVar, while the child
        # independent because Harness still receives ``usage=None`` for Workers.
        with bind_research_request_state(research_state):
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
                # #region agent log
                debug_runtime_log(
                    hypothesis_id="H5",
                    location="pydantic_executor.py:_classified_native_events.timeout",
                    message="native stream timed out",
                    data={"event_count": native_event_count},
                    run_id=str(request.request_id),
                )
                # #endregion agent log
                raise
            except ModelAPIError as exc:
                stream_error_code = _product_safe_model_error(exc).code
                # #region agent log
                debug_runtime_log(
                    hypothesis_id="H5",
                    location="pydantic_executor.py:_classified_native_events.model_error",
                    message="native stream model error",
                    data={"event_count": native_event_count, "error_type": type(exc).__name__},
                    run_id=str(request.request_id),
                )
                # #endregion agent log
                raise
            except UsageLimitExceeded:
                stream_error_code = "MODEL_CALL_LIMIT_REACHED"
                # #region agent log
                debug_runtime_log(
                    hypothesis_id="H5",
                    location="pydantic_executor.py:_classified_native_events.usage_error",
                    message="native stream usage limit reached",
                    data={"event_count": native_event_count},
                    run_id=str(request.request_id),
                )
                # #endregion agent log
                raise

    events = adapter.transform_stream(
        _classified_native_events(),
        on_complete=_on_complete,
    )

    async for chunk in adapter.encode_stream(events):
        payload = decode_event(chunk)
        if payload is not None and payload.get("type") == "finish":
            for url in source_urls:
                yield encode_event("source-url", sourceId=url, url=url)
        if on_terminal is not None:
            if payload is not None and payload.get("type") in {"abort", "error"}:
                kind = payload["type"]
                reason = (
                    stream_error_code
                    if kind == "error"
                    else payload.get("reason")
                )
                replacement = await on_terminal(kind, reason)
                yield replacement
                continue
        yield chunk
