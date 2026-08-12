"""Runtime clock semantic capability.

纯函数：为一次模型调用生成权威时间上下文。v8 中不依赖任何 Agent Framework；
Pydantic AI milestone 会把它接到 system prompt / capability。
"""

from datetime import datetime
from zoneinfo import ZoneInfo

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
