import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

AgentExecutionErrorCode = Literal[
    "AGENT_LOOP_LIMIT_REACHED",
    "MODEL_CALL_LIMIT_REACHED",
    "MODEL_TIMEOUT",
    "MODEL_RATE_LIMITED",
    "MODEL_UNAVAILABLE",
]


@dataclass(frozen=True, slots=True)
class AgentExecutionResult:
    content: str


@dataclass(slots=True)
class AgentExecutionError(Exception):
    code: AgentExecutionErrorCode
    retryable: bool = True


class AgentExecutor(Protocol):
    """Framework-neutral port between Product Runtime and Agent execution.

    Product Runtime（ChatService）只依赖这个边界；具体实现（Legacy Deep Agents、
    未来的 Pydantic AI）只能实现 execute，不能反向拥有 Product RequestRun、
    Authorization、Quota、Billing 或 Conversation 的 SOT。
    """

    async def execute(
        self,
        *,
        request_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message: str,
        deadline_at: datetime,
    ) -> AgentExecutionResult: ...


class AgentRuntimeNotConfigured(RuntimeError):
    pass


def get_agent_executor() -> AgentExecutor:
    """Return the configured AgentExecutor implementation.

    v8 clean baseline：暂无 Agent Framework 实现，抛 AgentRuntimeNotConfigured，
    /chat 由 API 层映射为 503。Pydantic AI milestone 会替换这里的 provider。
    """
    raise AgentRuntimeNotConfigured("Agent runtime is not configured")
