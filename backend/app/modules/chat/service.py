import asyncio
import uuid
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import BaseMessage
from langgraph.errors import GraphRecursionError
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from app.agents.travel import build_travel_agent
from app.core.config import settings
from app.modules.chat.schema import AgentChatResponse

ChatErrorCode = Literal[
    "REQUEST_DEADLINE_EXCEEDED",
    "AGENT_LOOP_LIMIT_REACHED",
    "MODEL_TIMEOUT",
    "MODEL_RATE_LIMITED",
    "MODEL_UNAVAILABLE",
]


@dataclass(slots=True)
class ChatExecutionError(Exception):
    code: ChatErrorCode
    message: str
    retryable: bool
    status_code: int


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


class ChatService:
    async def chat(self, *, request_id: uuid.UUID, message: str) -> AgentChatResponse:
        agent = build_travel_agent(
            request_id=str(request_id),
            metadata={"endpoint": "chat"},
        )

        try:
            async with asyncio.timeout(settings.REQUEST_DEADLINE_SECONDS):
                result = await agent.ainvoke(
                    {"messages": [{"role": "user", "content": message}]},
                    config={"recursion_limit": settings.AGENT_RECURSION_LIMIT},
                )
        except TimeoutError as exc:
            raise ChatExecutionError(
                code="REQUEST_DEADLINE_EXCEEDED",
                message="请求处理超时，请稍后重试。",
                retryable=True,
                status_code=504,
            ) from exc
        except GraphRecursionError as exc:
            raise ChatExecutionError(
                code="AGENT_LOOP_LIMIT_REACHED",
                message="规划步骤超过安全上限，请简化问题后重试。",
                retryable=False,
                status_code=422,
            ) from exc
        except APITimeoutError as exc:
            raise ChatExecutionError(
                code="MODEL_TIMEOUT",
                message="模型响应超时，请稍后重试。",
                retryable=True,
                status_code=504,
            ) from exc
        except RateLimitError as exc:
            raise ChatExecutionError(
                code="MODEL_RATE_LIMITED",
                message="当前规划服务繁忙，请稍后重试。",
                retryable=True,
                status_code=429,
            ) from exc
        except (APIConnectionError, APIStatusError) as exc:
            raise ChatExecutionError(
                code="MODEL_UNAVAILABLE",
                message="当前规划服务暂时不可用，请稍后重试。",
                retryable=True,
                status_code=503,
            ) from exc

        messages = result.get("messages")
        if not messages or not isinstance(messages[-1], BaseMessage):
            raise RuntimeError("Agent returned no final message")
        content = _message_text(messages[-1])
        if not content:
            raise RuntimeError("Agent returned an empty final message")
        return AgentChatResponse(request_id=request_id, content=content)
