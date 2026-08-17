import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

from app.agent.usage import AgentUsage

AgentExecutionErrorCode = Literal[
    "AGENT_LOOP_LIMIT_REACHED",
    "MODEL_CALL_LIMIT_REACHED",
    "MODEL_TIMEOUT",
    "MODEL_RATE_LIMITED",
    "MODEL_UNAVAILABLE",
]
AgentStreamTerminalKind = Literal["abort", "error"]


@dataclass(frozen=True, slots=True)
class AgentMessage:
    """A single durable product message projected into agent history."""

    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class AgentExecutionRequest:
    """Server-authoritative execution input.

    ``message`` is the current user input; ``history`` is the durable product
    history *before* the current request (must NOT include the current message,
    otherwise the current turn is sent twice).
    """

    request_id: uuid.UUID
    conversation_id: uuid.UUID
    message: str
    history: tuple[AgentMessage, ...]
    deadline_at: datetime
    enable_web_search: bool = True
    enable_thinking: bool = True


@dataclass(frozen=True, slots=True)
class AgentExecutionResult:
    content: str
    reasoning_summary: str | None = None
    source_urls: tuple[str, ...] = ()
    usage: AgentUsage = field(default_factory=AgentUsage)


@dataclass(slots=True)
class AgentExecutionError(Exception):
    code: AgentExecutionErrorCode
    retryable: bool = True


class AgentRuntimeNotConfigured(RuntimeError):
    pass


class AgentExecutor(Protocol):
    """Framework-neutral port between Product Runtime and Agent execution.

    Product Runtime（ChatService）只依赖这个边界；具体实现（Pydantic AI）只能实现
    execute，不能反向拥有 Product RequestRun、Authorization、Quota、Billing 或
    Conversation 的 SOT。
    """

    async def execute(
        self,
        request: AgentExecutionRequest,
    ) -> AgentExecutionResult: ...

def get_agent_executor() -> AgentExecutor:
    """Return the configured AgentExecutor implementation."""
    from app.agent.pydantic_executor import get_agent_executor as _get_pydantic

    return _get_pydantic()


def stream_vercel_events(
    request: AgentExecutionRequest,
    *,
    on_complete: Callable[[AgentExecutionResult], Awaitable[None]] | None,
    on_terminal: Callable[
        [AgentStreamTerminalKind, str | None], Awaitable[str]
    ]
    | None = None,
) -> AsyncIterator[str]:
    """Stream a chat turn as Vercel AI UI protocol SSE strings.

    This is a UI protocol adapter, not a framework-neutral domain event port.
    The framework-neutral boundary between Product Runtime and Agent execution
    is ``AgentExecutor.execute``; this function binds the additional streaming
    contract to the Vercel AI SDK data stream format.

    Delegates to the PydanticAI ``VercelAIAdapter``; ``on_complete`` receives the
    framework-neutral final plus an optional Product-visible reasoning summary and
    is awaited before the finish chunk so Product can COMMIT durable state first.
    """
    from app.agent.pydantic_executor import stream_vercel_events as _stream

    return _stream(request, on_complete=on_complete, on_terminal=on_terminal)
