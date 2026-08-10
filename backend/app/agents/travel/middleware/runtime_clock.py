"""Runtime clock middleware for the Travel Agent cognitive core."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from app.core.config import settings

_WEEKDAY_NAMES = (
    "星期一",
    "星期二",
    "星期三",
    "星期四",
    "星期五",
    "星期六",
    "星期日",
)


def runtime_clock_context(
    *,
    now: datetime | None = None,
    timezone_name: str | None = None,
) -> str:
    """Return the authoritative runtime clock context for one model call."""
    timezone = ZoneInfo(timezone_name or settings.APP_TIMEZONE)
    if now is None:
        current = datetime.now(timezone)
    elif now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    else:
        current = now.astimezone(timezone)

    return (
        "# Runtime Current Date\n"
        f"当前日期：{current:%Y-%m-%d}\n"
        f"当前星期：{_WEEKDAY_NAMES[current.weekday()]}\n"
        f"当前时间：{current:%H:%M:%S}\n"
        f"当前时区：{timezone.key}\n"
        f"当前年份：{current:%Y}\n\n"
        "以上 Runtime 时间是处理相对日期、最新信息和时效性 Research 的唯一时间基准。"
    )


def _append_runtime_context(request: ModelRequest) -> ModelRequest:
    context = runtime_clock_context()
    current_content = (
        request.system_message.content if request.system_message is not None else ""
    )

    if isinstance(current_content, str):
        content: Any = (
            f"{current_content}\n\n{context}" if current_content else context
        )
    else:
        content = [*current_content, {"type": "text", "text": context}]

    return request.override(system_message=SystemMessage(content=content))


class RuntimeClockMiddleware(AgentMiddleware):
    """Inject current time context immediately before every model call."""

    name = "RuntimeClockMiddleware"

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(_append_runtime_context(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(_append_runtime_context(request))
