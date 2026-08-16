"""Configuration helpers owned by the Agent tool layer."""

from __future__ import annotations

from app.core.config import settings


def require_tool_key(name: str) -> str:
    """Return one configured provider key without exposing it to a tool result."""
    value = getattr(settings, name, None)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"缺少环境变量 {name}")
    return value


def searxng_base_url() -> str:
    """Self-hosted SearXNG endpoint without a trailing slash."""
    return settings.SEARXNG_BASE_URL.rstrip("/")
