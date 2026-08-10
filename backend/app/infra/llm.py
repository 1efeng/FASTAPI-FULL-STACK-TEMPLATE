from collections.abc import Mapping
from typing import Literal

from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI
from pydantic import SecretStr

from app.core.config import settings

AgentRole = Literal["main", "researcher"]

_client: AsyncOpenAI | None = None


def _gateway_base_url() -> str:
    return f"{settings.LITELLM_BASE_URL.rstrip('/')}/v1"


def init_llm() -> AsyncOpenAI:
    """Create the process-scoped OpenAI-compatible LiteLLM client."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.LITELLM_SERVICE_KEY,
            base_url=_gateway_base_url(),
            timeout=settings.REQUEST_DEADLINE_SECONDS,
            max_retries=0,
        )
    return _client


def get_llm() -> AsyncOpenAI:
    if _client is None:
        raise RuntimeError("LiteLLM client has not been initialized")
    return _client


def build_model(
    *,
    request_id: str,
    agent_role: AgentRole,
    trace_id: str | None = None,
    metadata: Mapping[str, str | int | float | bool | None] | None = None,
) -> ChatOpenAI:
    """Build a request-scoped LangChain model backed only by LiteLLM."""
    if not request_id.strip():
        raise ValueError("request_id must not be empty")

    trace_metadata: dict[str, str | int | float | bool | None] = {
        "request_id": request_id,
        "trace_id": trace_id,
        "agent_role": agent_role,
        "logical_model": settings.LLM_LOGICAL_MODEL,
    }
    if metadata:
        trace_metadata.update(metadata)

    return ChatOpenAI(
        model=settings.LLM_LOGICAL_MODEL,
        api_key=SecretStr(settings.LITELLM_SERVICE_KEY),
        base_url=_gateway_base_url(),
        timeout=settings.REQUEST_DEADLINE_SECONDS,
        max_retries=0,
        use_responses_api=False,
        default_headers={"X-Client-Request-Id": request_id},
        extra_body={"metadata": trace_metadata},
        metadata=trace_metadata,
        tags=["travel-agent", agent_role],
    )


async def close_llm() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
