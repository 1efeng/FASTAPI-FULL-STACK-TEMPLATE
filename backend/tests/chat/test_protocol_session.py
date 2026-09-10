import asyncio
import json
from contextlib import suppress
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from app.chat.protocol.session import ThreadSession


def _command(text: str = "你好") -> dict[str, Any]:
    return {
        "id": 1,
        "method": "run.start",
        "params": {
            "assistantId": "agent",
            "input": {
                "messages": [
                    {"type": "human", "content": text, "id": "human-1"}
                ]
            },
        },
    }


def _event_from_sse(frame: str) -> dict[str, Any]:
    data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
    return json.loads(data_line.removeprefix("data: "))


class StreamingAgent:
    async def astream_events(self, input: dict[str, Any], **_: Any):
        yield {
            "event": "on_chat_model_stream",
            "run_id": "model-1",
            "name": "ChatOpenAI",
            "metadata": {"langgraph_node": "model"},
            "data": {"chunk": AIMessageChunk(content="你", id="ai-1")},
        }
        yield {
            "event": "on_chat_model_stream",
            "run_id": "model-1",
            "name": "ChatOpenAI",
            "metadata": {"langgraph_node": "model"},
            "data": {"chunk": AIMessageChunk(content="好", id="ai-1")},
        }
        yield {
            "event": "on_chat_model_end",
            "run_id": "model-1",
            "name": "ChatOpenAI",
            "metadata": {"langgraph_node": "model"},
            "data": {},
        }
        yield {
            "event": "on_chain_end",
            "run_id": "graph-1",
            "name": "LangGraph",
            "parent_ids": [],
            "data": {
                "output": {
                    "messages": [
                        *input["messages"],
                        AIMessage(content="你好", id="ai-1"),
                    ]
                }
            },
        }


class ToolAgent:
    async def astream_events(self, input: dict[str, Any], **_: Any):
        yield {
            "event": "on_tool_start",
            "run_id": "tool-run-1",
            "name": "search_docs",
            "metadata": {"langgraph_node": "tools", "tool_call_id": "call-1"},
            "data": {"input": {"q": "LangGraph"}},
        }
        yield {
            "event": "on_tool_end",
            "run_id": "tool-run-1",
            "name": "search_docs",
            "metadata": {"langgraph_node": "tools", "tool_call_id": "call-1"},
            "data": {"output": {"ok": True}},
        }
        yield {
            "event": "on_chain_end",
            "run_id": "graph-1",
            "name": "LangGraph",
            "parent_ids": [],
            "data": {
                "output": {
                    "messages": [
                        *input["messages"],
                        AIMessage(content="完成", id="ai-2"),
                    ]
                }
            },
        }


class SlowAgent:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def astream_events(self, input: dict[str, Any], **_: Any):
        self.started.set()
        await self.release.wait()
        yield {
            "event": "on_chain_end",
            "run_id": "graph-1",
            "name": "LangGraph",
            "parent_ids": [],
            "data": {
                "output": {
                    "messages": [
                        *input["messages"],
                        AIMessage(content="完成", id="ai-slow"),
                    ]
                }
            },
        }


@pytest.mark.asyncio
async def test_run_streams_messages_and_hydrates_state() -> None:
    session = ThreadSession("thread-1", agent_factory=lambda: StreamingAgent())

    response = await session.handle_command(_command())
    assert response["type"] == "success"
    assert response["result"]["runId"]

    assert session.active_run is not None
    await session.active_run.task

    state = session.state()
    assert [message["type"] for message in state["values"]["messages"]] == [
        "human",
        "ai",
    ]
    assert state["values"]["messages"][-1]["content"] == "你好"

    stream = session.event_stream(
        {"channels": ["messages", "lifecycle"], "since": 0}
    )
    events = []
    try:
        for _ in range(8):
            events.append(_event_from_sse(await asyncio.wait_for(anext(stream), 1)))
    finally:
        await stream.aclose()

    message_events = [
        event["params"]["data"]["event"]
        for event in events
        if event["method"] == "messages"
    ]
    assert "message-start" in message_events
    assert "content-block-delta" in message_events
    assert "message-finish" in message_events
    assert any(
        event["method"] == "lifecycle"
        and event["params"]["data"]["event"] == "completed"
        for event in events
    )


@pytest.mark.asyncio
async def test_tool_lifecycle_is_exposed_on_tools_channel() -> None:
    session = ThreadSession("thread-tools", agent_factory=lambda: ToolAgent())
    await session.handle_command(_command("查一下"))
    assert session.active_run is not None
    await session.active_run.task

    stream = session.event_stream({"channels": ["tools"], "since": 0})
    try:
        started = _event_from_sse(await asyncio.wait_for(anext(stream), 1))
        finished = _event_from_sse(await asyncio.wait_for(anext(stream), 1))
    finally:
        await stream.aclose()

    assert started["params"]["data"] == {
        "event": "tool-started",
        "toolCallId": "call-1",
        "toolName": "search_docs",
        "input": {"q": "LangGraph"},
    }
    assert finished["params"]["data"]["event"] == "tool-finished"
    assert finished["params"]["data"]["toolCallId"] == "call-1"


@pytest.mark.asyncio
async def test_disconnect_does_not_cancel_active_run() -> None:
    agent = SlowAgent()
    session = ThreadSession("thread-reconnect", agent_factory=lambda: agent)
    await session.handle_command(_command("慢一点"))
    await asyncio.wait_for(agent.started.wait(), 1)

    stream = session.event_stream({"channels": ["lifecycle"], "since": 0})
    await asyncio.wait_for(anext(stream), 1)
    await stream.aclose()

    assert session.active_run is not None
    assert not session.active_run.task.done()

    agent.release.set()
    await asyncio.wait_for(session.active_run.task, 1)
    assert session.active_run.status == "completed"


@pytest.mark.asyncio
async def test_cancel_stops_the_server_side_run() -> None:
    agent = SlowAgent()
    session = ThreadSession("thread-stop", agent_factory=lambda: agent)
    response = await session.handle_command(_command("不要结束"))
    run_id = response["result"]["runId"]
    await asyncio.wait_for(agent.started.wait(), 1)

    assert await session.cancel_run(run_id)
    assert session.active_run is not None
    with suppress(asyncio.CancelledError):
        await session.active_run.task

    assert session.active_run.status == "interrupted"
    assert not await session.cancel_run(run_id)


@pytest.mark.asyncio
async def test_second_run_is_rejected_while_thread_is_active() -> None:
    agent = SlowAgent()
    session = ThreadSession("thread-single-run", agent_factory=lambda: agent)
    await session.handle_command(_command("第一个"))
    await asyncio.wait_for(agent.started.wait(), 1)

    second = await session.handle_command(_command("第二个"))
    assert second["type"] == "error"
    assert second["error"] == "invalid_argument"

    assert session.active_run is not None
    session.active_run.task.cancel()
    with suppress(asyncio.CancelledError):
        await session.active_run.task
