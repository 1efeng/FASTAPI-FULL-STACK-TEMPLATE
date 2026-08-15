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
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal

from openai import APITimeoutError, AsyncOpenAI
from pydantic_ai import Agent, AgentRunResult, UsageLimits
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError, UsageLimitExceeded
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    UserPromptPart,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.request_types import SubmitMessage, TextUIPart, UIMessage

from app.agent.capabilities.travel import build_travel_capabilities
from app.agent.context.runtime_clock import runtime_clock_context
from app.agent.executor import (
    AgentExecutionError,
    AgentExecutionErrorCode,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutor,
    AgentStreamTerminalKind,
)
from app.agent.prompts import MAIN_TRAVEL_INSTRUCTIONS
from app.agent.usage import AgentModelCallUsage, AgentTokenUsage, AgentUsage
from app.core.config import settings

_GENERIC_CHAT_INSTRUCTIONS = (
    "你是「行伴」，一位专业的旅行规划助手。"
    "用用户使用的语言简洁、准确地回答问题；不编造实时信息。"
)

_MODEL_TIMEOUT_STATUS_CODES = frozenset({408, 504})

# Must stay paired with the exact ``ai`` / ``@ai-sdk/react`` versions in the
# frontend manifest and the protocol fixture in the backend test suite.
VERCEL_AI_SDK_VERSION: Literal[7] = 7


def _runtime_clock_instructions() -> str:
    """Adapt the framework-neutral clock into per-run dynamic instructions."""
    return runtime_clock_context()


def _litellm_openai_base_url() -> str:
    """Return the OpenAI-compatible base URL of the LiteLLM gateway.

    ``LITELLM_BASE_URL`` is the gateway root (e.g. ``http://litellm:4000``); the
    OpenAI client appends ``/chat/completions``, so the path must end in ``/v1``.
    """
    base = settings.LITELLM_BASE_URL.rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


def _model_rpc_settings() -> ModelSettings:
    """Return the timeout applied independently to every model request."""
    return ModelSettings(timeout=settings.LITELLM_CLIENT_TIMEOUT_SECONDS)


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
def get_chat_agent() -> Agent:
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
    model = OpenAIChatModel(
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
            researcher_model=model,
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
) -> AgentUsage:
    """Map new PydanticAI responses into the framework-neutral usage contract."""
    responses = (
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
        for call_index, message in enumerate(responses)
    )
    return AgentUsage(
        model_calls=model_calls,
        tool_calls=result.usage.tool_calls,
        unattributed_model_requests=max(
            0,
            result.usage.requests - len(model_calls),
        ),
    )


def _to_reasoning_summary(result: AgentRunResult[Any]) -> str | None:
    """Collect only textual thinking already projected to the public UI stream.

    Provider signatures/details and framework scratchpad are deliberately omitted.
    The Product contract stores this as an optional display summary, never as agent
    history and never as a provider round-trip artifact.
    """
    summaries = [
        part.content.strip()
        for message in result.new_messages()
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ThinkingPart) and part.content.strip()
    ]
    summary = "\n\n".join(summaries).strip()
    return summary or None


@dataclass(slots=True)
class _ReasoningDurationTracker:
    """Measure only intervals bracketed by public Vercel reasoning chunks."""

    active_parts: dict[str, int] = field(default_factory=dict)
    elapsed_ns: int = 0

    def observe(self, payload: dict[str, Any], *, now_ns: int | None = None) -> None:
        event_type = payload.get("type")
        part_id = payload.get("id")
        if not isinstance(part_id, str):
            return
        observed_at = time.monotonic_ns() if now_ns is None else now_ns
        if event_type == "reasoning-start":
            self.active_parts.setdefault(part_id, observed_at)
        elif event_type == "reasoning-end":
            started_at = self.active_parts.pop(part_id, None)
            if started_at is not None:
                self.elapsed_ns += max(0, observed_at - started_at)

    @property
    def duration_ms(self) -> int | None:
        if self.elapsed_ns <= 0:
            return None
        return max(1, (self.elapsed_ns + 999_999) // 1_000_000)


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
        self._logical_model = logical_model or settings.LLM_LOGICAL_MODEL

    async def execute(
        self,
        request: AgentExecutionRequest,
    ) -> AgentExecutionResult:
        message_history = _to_model_messages(request)
        try:
            result = await self._agent.run(
                request.message,
                message_history=message_history,
                run_id=str(request.request_id),
                usage_limits=_main_usage_limits(),
            )
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
            usage=_to_agent_usage(result, logical_model=self._logical_model),
        )


def get_agent_executor() -> AgentExecutor:
    """Return the configured PydanticAI executor (non-streaming).

    Kept framework-neutral: the returned object satisfies the AgentExecutor port
    defined in ``app.agent.executor``.
    """
    return PydanticAIExecutor()


async def dispatch_vercel_spike(request: Any) -> Any:
    """Serve the temporary raw adapter compatibility endpoint."""
    return await VercelAIAdapter.dispatch_request(
        request,
        agent=get_chat_agent(),
        sdk_version=VERCEL_AI_SDK_VERSION,
    )


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
        server_message_id=str(request.request_id),
    )

    message_history = _to_model_messages(request)
    reasoning_timer = _ReasoningDurationTracker()
    stream_error_code: AgentExecutionErrorCode | None = None

    async def _on_complete(result: AgentRunResult[Any]) -> None:
        if on_complete is None:
            return
        output = result.output
        if isinstance(output, str) and output.strip():
            await on_complete(
                AgentExecutionResult(
                    content=output,
                    reasoning_summary=_to_reasoning_summary(result),
                    reasoning_duration_ms=reasoning_timer.duration_ms,
                    usage=_to_agent_usage(
                        result, logical_model=settings.LLM_LOGICAL_MODEL
                    ),
                )
            )

    native_events = adapter.run_stream_native(
        message_history=message_history,
        run_id=str(request.request_id),
        model_settings=_model_rpc_settings(),
        usage_limits=_main_usage_limits(),
    )

    async def _classified_native_events() -> AsyncIterator[Any]:
        nonlocal stream_error_code
        try:
            async for event in native_events:
                yield event
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            stream_error_code = "MODEL_TIMEOUT"
            raise
        except ModelAPIError as exc:
            stream_error_code = _product_safe_model_error(exc).code
            raise
        except UsageLimitExceeded:
            stream_error_code = "MODEL_CALL_LIMIT_REACHED"
            raise

    events = adapter.transform_stream(
        _classified_native_events(),
        on_complete=_on_complete,
    )

    async for chunk in adapter.encode_stream(events):
        try:
            data = chunk.removeprefix("data: ").removesuffix("\n\n")
            payload = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            payload = None
        if isinstance(payload, dict):
            reasoning_timer.observe(payload)
        if on_terminal is not None:
            if isinstance(payload, dict) and payload.get("type") in {"abort", "error"}:
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
