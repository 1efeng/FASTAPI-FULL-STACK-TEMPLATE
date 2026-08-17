"""Lifecycle-aware streaming: encode PydanticAI text into the AI SDK data stream
protocol (v7) and enforce the terminal gate.

The AI SDK Data Stream protocol (SSE + JSON objects) is the wire format. The
Store receives opaque encoded strings only — it never parses the protocol.

Terminal gate (P0-5): the ``finish``/``abort``/``error`` UI terminal is emitted
only after the corresponding Product transaction COMMITs.
"""

from __future__ import annotations

from app.infra.vercel_protocol import done_marker as _done_marker
from app.infra.vercel_protocol import encode_event


def sse_part(payload: dict[str, object]) -> str:
    event_type = payload.pop("type")
    return encode_event(event_type, **payload)


def start_part(message_id: str) -> str:
    return sse_part({"type": "start", "messageId": message_id})


def text_start_part(part_id: str) -> str:
    return sse_part({"type": "text-start", "id": part_id})


def text_delta_part(part_id: str, delta: str) -> str:
    return sse_part({"type": "text-delta", "id": part_id, "delta": delta})


def text_end_part(part_id: str) -> str:
    return sse_part({"type": "text-end", "id": part_id})


def finish_part() -> str:
    return sse_part({"type": "finish"})


def error_part(error_text: str) -> str:
    return sse_part({"type": "error", "errorText": error_text})


def abort_part(reason: str | None = None) -> str:
    payload: dict[str, object] = {"type": "abort"}
    if reason:
        payload["reason"] = reason
    return sse_part(payload)


def source_url_part(url: str) -> str:
    return sse_part({"type": "source-url", "sourceId": url, "url": url})


def done_marker() -> str:
    return _done_marker()
