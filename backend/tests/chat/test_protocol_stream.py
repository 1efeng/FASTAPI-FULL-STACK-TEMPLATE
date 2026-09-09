import json
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessageChunk, BaseMessage, SystemMessage

from app.chat.protocol.stream import ui_message_stream


class FakeStreamingModel:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self.received_messages: list[BaseMessage] = []

    async def astream(self, messages: list[BaseMessage]) -> AsyncIterator[AIMessageChunk]:
        self.received_messages = messages
        for text in self.chunks:
            yield AIMessageChunk(content=text)


async def collect_chunks(model: FakeStreamingModel) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    ui_messages = [
        {
            "id": "user-1",
            "role": "user",
            "parts": [{"type": "text", "text": "你好"}],
        }
    ]

    async for line in ui_message_stream(ui_messages, model=model):
        payload = line.removeprefix("data: ").strip()
        if payload and payload != "[DONE]":
            chunks.append(json.loads(payload))

    return chunks


async def test_streams_ai_sdk_ui_message_protocol() -> None:
    model = FakeStreamingModel(["你", "好"])

    chunks = await collect_chunks(model)
    chunk_types = [chunk["type"] for chunk in chunks]

    assert chunk_types == [
        "start",
        "start-step",
        "text-start",
        "text-delta",
        "text-delta",
        "text-end",
        "finish-step",
        "finish",
    ]
    assert "".join(
        chunk["delta"] for chunk in chunks if chunk["type"] == "text-delta"
    ) == "你好"
    assert isinstance(model.received_messages[0], SystemMessage)


class BrokenStreamingModel:
    async def astream(self, messages: list[BaseMessage]) -> AsyncIterator[AIMessageChunk]:
        raise RuntimeError("provider failed")
        yield AIMessageChunk(content="unreachable")


async def test_provider_error_is_exposed_as_ai_sdk_error_chunk() -> None:
    chunks: list[dict[str, Any]] = []

    async for line in ui_message_stream(
        [{"role": "user", "parts": [{"type": "text", "text": "hi"}]}],
        model=BrokenStreamingModel(),
    ):
        payload = line.removeprefix("data: ").strip()
        if payload and payload != "[DONE]":
            chunks.append(json.loads(payload))

    assert chunks[-1] == {
        "type": "error",
        "errorText": "模型调用失败，请稍后重试。",
    }
