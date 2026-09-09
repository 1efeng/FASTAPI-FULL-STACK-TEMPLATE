from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings

TRAVEL_PLANNING_SKILL_PATH = (
    Path(__file__).parent / "skills" / "travel-planning" / "SKILL.md"
)


@lru_cache
def load_travel_planning_skill() -> str:
    """Load the runtime travel-planning Skill used as the system instruction."""
    return TRAVEL_PLANNING_SKILL_PATH.read_text(encoding="utf-8").strip()


def system_message() -> SystemMessage:
    return SystemMessage(content=load_travel_planning_skill())


@lru_cache
def get_chat_model() -> BaseChatModel:
    """Create the LangChain ChatModel used by Chapter 1.

    `ChatOpenAI` is used as the provider adapter because the configured endpoint
    may be any OpenAI-compatible API. LangChain remains the application-facing
    model abstraction.
    """
    if settings.LLM_API_KEY is None:
        raise RuntimeError("LLM_API_KEY is not configured")

    kwargs: dict[str, object] = {
        "model": settings.LLM_MODEL,
        "api_key": settings.LLM_API_KEY.get_secret_value(),
        "streaming": True,
    }
    if settings.LLM_BASE_URL:
        kwargs["base_url"] = settings.LLM_BASE_URL

    return ChatOpenAI(**kwargs)
