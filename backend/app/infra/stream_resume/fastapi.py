from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse


def sse_response(
    stream: AsyncIterator[str],
    *,
    headers: dict[str, str] | None = None,
) -> StreamingResponse:
    """Thin SSE helper only; protocol-specific headers remain caller-owned."""

    response_headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    if headers:
        response_headers.update(headers)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers=response_headers,
    )
