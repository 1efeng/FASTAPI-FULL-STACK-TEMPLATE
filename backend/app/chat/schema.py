from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request shape emitted by AI SDK `DefaultChatTransport`.

    AI SDK may include additional top-level fields such as `id` or `trigger`;
    Pydantic ignores them. The backend keeps the native `messages` array so the
    protocol adapter, not the React client, owns the LangChain conversion.
    """

    messages: list[dict[str, Any]] = Field(min_length=1)
