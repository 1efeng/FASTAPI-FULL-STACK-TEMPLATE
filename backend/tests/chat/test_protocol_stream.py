import json
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessageChunk, BaseMessage, HumanMessage

from app.chat.protocol.stream import ui_message_stream


class FakeStreamingAgent:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self.received_messages: list[BaseMessage] = []
        self.stream_mode: str | None = None

    async def astream(
        self,
        payload: dict[str, Any],
        *,
        stream_mode: str,
    ) -> AsyncIterator[tuple[AIMessageChunk, dict[str, Any]]]:
        self.received_messages = payload["messages"]
        self.stream_mode = stream_mode
        for text in self.chunks:
            yield AIMessageChunk(content=text), {}


async def collect_chunks(agent: FakeStreamingAgent) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    ui_messages = [
        {
            "id": "user-1",
            "role": "user",
            "parts": [{"type": "text", "text": "你好"}],
        }
    ]

    async for line in ui_message_stream(ui_messages, agent=agent):
        payload = line.removeprefix("data: ").strip()
        if payload and payload != "[DONE]":
            chunks.append(json.loads(payload))

    return chunks


async def test_streams_ai_sdk_ui_message_protocol() -> None:
    agent = FakeStreamingAgent(["你", "好"])

    chunks = await collect_chunks(agent)
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
    assert agent.stream_mode == "messages"
    assert isinstance(agent.received_messages[0], HumanMessage)
    assert agent.received_messages[0].content == "你好"


class BrokenStreamingAgent:
    async def astream(
        self,
        payload: dict[str, Any],
        *,
        stream_mode: str,
    ) -> AsyncIterator[tuple[AIMessageChunk, dict[str, Any]]]:
        raise RuntimeError("provider failed")
        yield AIMessageChunk(content="unreachable"), {}


async def test_provider_error_is_exposed_as_ai_sdk_error_chunk() -> None:
    chunks: list[dict[str, Any]] = []

    async for line in ui_message_stream(
        [{"role": "user", "parts": [{"type": "text", "text": "hi"}]}],
        agent=BrokenStreamingAgent(),
    ):
        payload = line.removeprefix("data: ").strip()
        if payload and payload != "[DONE]":
            chunks.append(json.loads(payload))

    assert chunks[-1] == {
        "type": "error",
        "errorText": "模型调用失败，请稍后重试。",
    }
