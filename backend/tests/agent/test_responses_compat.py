"""Regression tests for the narrow Ark Responses stream compatibility shim."""

from __future__ import annotations

from typing import Any, Self, cast

import pytest
from openai import AsyncStream
from openai.types import responses

from app.agent.responses_compat import (
    _EmptyReasoningMarkerFilter,
)


class _FakeStream:
    def __init__(self, events: list[responses.ResponseStreamEvent]) -> None:
        self._events = iter(events)
        self.closed = False

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> responses.ResponseStreamEvent:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_empty_reasoning_marker_is_dropped_but_real_delta_survives() -> None:
    empty_marker = responses.ResponseReasoningSummaryPartAddedEvent(
        item_id="rs_1",
        output_index=0,
        summary_index=0,
        part={"type": "summary_text", "text": ""},
        sequence_number=1,
        type="response.reasoning_summary_part.added",
    )
    delta = responses.ResponseReasoningSummaryTextDeltaEvent(
        delta="正在核验",
        item_id="rs_1",
        output_index=0,
        sequence_number=2,
        summary_index=0,
        type="response.reasoning_summary_text.delta",
    )
    source = _FakeStream([empty_marker, delta])
    filtered = _EmptyReasoningMarkerFilter(
        cast(AsyncStream[responses.ResponseStreamEvent], cast(Any, source))
    )

    assert await anext(filtered) is delta
    await filtered.close()
    assert source.closed is True


@pytest.mark.asyncio
async def test_nonempty_reasoning_marker_is_preserved() -> None:
    marker = responses.ResponseReasoningSummaryPartAddedEvent(
        item_id="rs_1",
        output_index=0,
        summary_index=0,
        part={"type": "summary_text", "text": "已有摘要"},
        sequence_number=1,
        type="response.reasoning_summary_part.added",
    )
    source = _FakeStream([marker])
    filtered = _EmptyReasoningMarkerFilter(
        cast(AsyncStream[responses.ResponseStreamEvent], cast(Any, source))
    )

    assert await anext(filtered) is marker
