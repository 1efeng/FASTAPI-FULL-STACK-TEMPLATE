"""Vercel AI SDK data-stream SSE primitives.

Single source of truth for encoding/decoding the browser wire format so that
neither the Agent layer nor the Product chat layer re-implements ``json.dumps``
on encoded chunks. Chunks are otherwise opaque to transport (StreamResumeStore).
"""

from __future__ import annotations

import json
from typing import Any

_DONE_MARKER = "data: [DONE]\n\n"


def encode_event(event_type: str, **fields: Any) -> str:
    payload: dict[str, Any] = {"type": event_type, **fields}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def decode_event(chunk: str) -> dict[str, Any] | None:
    """Return the event payload of an encoded data chunk, or None when not an event."""
    if not chunk.startswith("data: ") or not chunk.endswith("\n\n"):
        return None
    try:
        data = chunk.removeprefix("data: ").removesuffix("\n\n")
        payload = json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def done_marker() -> str:
    return _DONE_MARKER
