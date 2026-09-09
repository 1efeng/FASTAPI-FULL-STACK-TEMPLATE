from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessageChunk

from app.agent.agent import get_agent
from app.chat.protocol.messages import to_langchain_messages

logger = logging.getLogger("app.chat.stream")

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "x-vercel-ai-ui-message-stream": "v1",
}


def sse(chunk: dict[str, Any]) -> str:
    """Encode one AI SDK UI Message Stream chunk as SSE."""
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


def _chunk_text(chunk: AIMessageChunk) -> str:
    """Normalize LangChain text chunks across provider content shapes."""
    content = chunk.content

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )

    return ""


async def ui_message_stream(
    ui_messages: list[dict[str, Any]],
    *,
    agent: Any | None = None,
) -> AsyncIterator[str]:
    """Stream LangChain text output using AI SDK's UI Message Stream protocol.

    This is the Chapter 1 text-chat implementation. The protocol boundary is
    already in its final location; later chapters extend this adapter with tool,
    reasoning and approval chunks instead of changing the frontend contract.
    """
    chat_agent = agent or get_agent()

    yield sse({"type": "start"})
    yield sse({"type": "start-step"})

    text_id = str(uuid.uuid4())
    text_started = False

    try:
        async for event in chat_agent.astream(
            {"messages": to_langchain_messages(ui_messages)},
            stream_mode="messages",
        ):
            chunk = event[0] if isinstance(event, tuple) else event
            if not isinstance(chunk, AIMessageChunk):
                continue

            text = _chunk_text(chunk)
            if not text:
                continue

            if not text_started:
                text_started = True
                yield sse({"type": "text-start", "id": text_id})

            yield sse({"type": "text-delta", "id": text_id, "delta": text})

    except Exception:  # noqa: BLE001 - provider errors must reach logs and the stream
        logger.exception("Chat model stream failed")
        yield sse(
            {
                "type": "error",
                "errorText": "模型调用失败，请稍后重试。",
            }
        )
        yield "data: [DONE]\n\n"
        return

    if text_started:
        yield sse({"type": "text-end", "id": text_id})

    yield sse({"type": "finish-step"})
    yield sse({"type": "finish"})
    yield "data: [DONE]\n\n"
