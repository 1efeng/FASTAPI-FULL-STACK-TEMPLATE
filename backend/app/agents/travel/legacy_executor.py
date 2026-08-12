"""Legacy Deep Agents adapter for the AgentExecutor port.

Commit 1 过渡实现：把旧的 Deep Agents / LangGraph runtime 包在 AgentExecutor
边界之后，让 Product Runtime（ChatService）不再感知具体 Agent Framework。

本文件在 v8 Commit 2 中被删除，由 Pydantic AI executor 取代。
"""

import uuid
from datetime import datetime
from typing import Any

from langchain.agents.middleware.model_call_limit import (
    ModelCallLimitExceededError,
)
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from app.agents.travel import build_travel_agent
from app.core.config import settings
from app.modules.chat.executor import (
    AgentExecutionError,
    AgentExecutionResult,
    AgentExecutor,
)


def _message_text(message: BaseMessage) -> str:
    if isinstance(message.content, str):
        return message.content.strip()

    parts: list[str] = []
    for block in message.content:
        if isinstance(block, str):
            parts.append(block)
        elif block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts).strip()


class LegacyDeepAgentExecutor:
    """Adapters the legacy Deep Agents runtime to the framework-neutral port.

    使用 conversation_id 作为 LangGraph thread identity：每个业务会话对应一个
    thread，Product schema 不暴露 LangGraph thread 概念。
    """

    def __init__(self) -> None:
        self._agent: Any | None = None

    async def execute(
        self,
        *,
        request_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message: str,
        deadline_at: datetime,
    ) -> AgentExecutionResult:
        del deadline_at  # 绝对 deadline 由 Product Runtime 强制执行
        if self._agent is None:
            self._agent = build_travel_agent(
                request_id=str(request_id),
                metadata={
                    "endpoint": "chat",
                    "conversation_id": str(conversation_id),
                },
            )

        config: RunnableConfig = {
            "recursion_limit": settings.AGENT_RECURSION_LIMIT,
            "configurable": {"thread_id": str(conversation_id)},
        }
        try:
            result = await self._agent.ainvoke(
                {"messages": [{"role": "user", "content": message}]},
                config=config,
            )
        except ModelCallLimitExceededError as exc:
            raise AgentExecutionError(
                code="MODEL_CALL_LIMIT_REACHED",
                retryable=False,
            ) from exc
        except GraphRecursionError as exc:
            raise AgentExecutionError(
                code="AGENT_LOOP_LIMIT_REACHED",
                retryable=False,
            ) from exc
        except APITimeoutError as exc:
            raise AgentExecutionError(code="MODEL_TIMEOUT") from exc
        except RateLimitError as exc:
            raise AgentExecutionError(code="MODEL_RATE_LIMITED") from exc
        except (APIConnectionError, APIStatusError) as exc:
            raise AgentExecutionError(code="MODEL_UNAVAILABLE") from exc

        messages = result.get("messages")
        if not messages or not isinstance(messages[-1], BaseMessage):
            raise RuntimeError("Agent returned no final message")
        content = _message_text(messages[-1])
        if not content:
            raise RuntimeError("Agent returned an empty final message")
        return AgentExecutionResult(content=content)


def get_legacy_executor() -> AgentExecutor:
    """Provider used by the API layer during the v8 transition."""
    return LegacyDeepAgentExecutor()
