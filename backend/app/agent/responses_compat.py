"""Narrow compatibility adapter for OpenAI-compatible Responses streams.

Ark DeepSeek V4 emits ``response.reasoning_summary_part.added`` before the first
summary text delta, with the summary part containing no ``text`` field. OpenAI's
SDK normalizes that to ``text=''``. PydanticAI 2.28 then rejects the empty
ThinkingPart before the real summary deltas arrive.

Filter only that empty marker event. All subsequent reasoning deltas, function
calls, text deltas, usage, and terminal events remain untouched.
"""

from __future__ import annotations

from typing import Self, cast

from openai import AsyncStream
from openai.types import responses
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import (
    OpenAIModelName,
    OpenAIResponsesModel,
    OpenAIResponsesModelSettings,
    OpenAIResponsesStreamedResponse,
)


class _EmptyReasoningMarkerFilter:
    """Async-stream proxy that drops only Ark's empty reasoning start marker."""

    def __init__(self, source: AsyncStream[responses.ResponseStreamEvent]) -> None:
        self._source = source
        self._iterator = source.__aiter__()

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> responses.ResponseStreamEvent:
        while True:
            event = await self._iterator.__anext__()
            if (
                isinstance(event, responses.ResponseReasoningSummaryPartAddedEvent)
                and not event.part.text
            ):
                continue
            return event

    async def close(self) -> None:
        await self._source.close()


class CompatibleOpenAIResponsesModel(OpenAIResponsesModel):
    """OpenAI Responses model with one provider-neutral empty-event tolerance."""

    async def _process_streamed_response(
        self,
        response: AsyncStream[responses.ResponseStreamEvent],
        model_settings: OpenAIResponsesModelSettings,
        model_request_parameters: ModelRequestParameters,
        *,
        expected_model_name: OpenAIModelName | None = None,
        expected_response_id: str | None = None,
    ) -> OpenAIResponsesStreamedResponse:
        filtered = _EmptyReasoningMarkerFilter(response)
        return await super()._process_streamed_response(
            cast(AsyncStream[responses.ResponseStreamEvent], filtered),
            model_settings,
            model_request_parameters,
            expected_model_name=expected_model_name,
            expected_response_id=expected_response_id,
        )
