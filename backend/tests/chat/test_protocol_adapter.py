from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app.chat.protocol.adapter import (
    AgentEventAdapter,
    input_messages,
    protocol_message,
    run_completed,
    run_failed,
    run_interrupted,
    run_started,
    serialize_message,
    serialize_state,
)


def test_model_stream_is_converted_to_message_protocol_events() -> None:
    adapter = AgentEventAdapter()

    first = adapter.adapt(
        {
            "event": "on_chat_model_stream",
            "run_id": "model-1",
            "name": "ChatOpenAI",
            "metadata": {"langgraph_node": "model"},
            "data": {"chunk": AIMessageChunk(content="你", id="ai-1")},
        }
    )
    second = adapter.adapt(
        {
            "event": "on_chat_model_stream",
            "run_id": "model-1",
            "name": "ChatOpenAI",
            "metadata": {"langgraph_node": "model"},
            "data": {"chunk": AIMessageChunk(content="好", id="ai-1")},
        }
    )
    finished = adapter.adapt(
        {
            "event": "on_chat_model_end",
            "run_id": "model-1",
            "name": "ChatOpenAI",
            "metadata": {"langgraph_node": "model"},
            "data": {},
        }
    )

    assert [event.method for event in first] == ["messages", "messages", "messages"]
    assert first[0].data == {"event": "message-start", "role": "ai", "id": "ai-1"}
    assert first[2].data["delta"]["text"] == "你"
    assert second[0].data["delta"]["text"] == "好"
    assert finished[0].data["content"]["text"] == "你好"
    assert finished[1].data == {"event": "message-finish"}


def test_tool_events_are_converted_without_runtime_state() -> None:
    adapter = AgentEventAdapter()

    started = adapter.adapt(
        {
            "event": "on_tool_start",
            "run_id": "tool-run-1",
            "name": "search_docs",
            "metadata": {"langgraph_node": "tools", "tool_call_id": "call-1"},
            "data": {"input": {"query": "LangGraph"}},
        }
    )
    finished = adapter.adapt(
        {
            "event": "on_tool_end",
            "run_id": "tool-run-1",
            "name": "search_docs",
            "metadata": {"langgraph_node": "tools"},
            "data": {"output": {"ok": True}},
        }
    )

    assert started[0].method == "tools"
    assert started[0].data == {
        "event": "tool-started",
        "tool_call_id": "call-1",
        "tool_name": "search_docs",
        "input": {"query": "LangGraph"},
    }
    assert finished[0].data == {
        "event": "tool-finished",
        "tool_call_id": "call-1",
        "output": {"ok": True},
    }


def test_tool_error_and_unknown_events() -> None:
    adapter = AgentEventAdapter()
    adapter.adapt(
        {
            "event": "on_tool_start",
            "run_id": "tool-run-2",
            "name": "search_docs",
            "metadata": {"tool_call_id": "call-2"},
            "data": {"input": {}},
        }
    )

    failed = adapter.adapt(
        {
            "event": "on_tool_error",
            "run_id": "tool-run-2",
            "name": "search_docs",
            "data": {"error": RuntimeError("boom")},
        }
    )

    assert failed[0].method == "tools"
    assert failed[0].data["event"] == "tool-error"
    assert failed[0].data["tool_call_id"] == "call-2"
    assert "boom" in failed[0].data["message"]
    assert adapter.adapt({"event": "on_chain_start", "data": {}}) == []


def test_protocol_message_and_run_lifecycle_helpers() -> None:
    started, running = run_started("run-1")
    completed = run_completed("run-1")
    interrupted = run_interrupted("run-1")
    failed = run_failed("run-1", RuntimeError("failed"))

    wire = protocol_message(started)
    assert wire["method"] == "lifecycle"
    assert wire["params"]["namespace"] == []
    assert isinstance(wire["params"]["timestamp"], int)
    assert wire["params"]["data"]["event"] == "started"
    assert running.data["event"] == "running"
    assert completed.data["event"] == "completed"
    assert interrupted.data["event"] == "interrupted"
    assert failed.data["event"] == "failed"
    assert failed.data["error"] == "failed"


def test_input_messages_uses_langchain_message_conversion() -> None:
    messages = input_messages(
        {
            "messages": [
                {"type": "human", "content": "hello", "id": "human-1"},
            ]
        }
    )

    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)
    assert messages[0].content == "hello"
    assert input_messages({}) == []

    with pytest.raises(ValueError, match="must be an object"):
        input_messages(None)
    with pytest.raises(ValueError, match="must be an array"):
        input_messages({"messages": "not-a-list"})


def test_serialize_message_preserves_tool_information() -> None:
    ai_message = AIMessage(
        content="calling",
        id="ai-1",
        tool_calls=[
            {
                "name": "search_docs",
                "args": {"query": "x"},
                "id": "call-1",
                "type": "tool_call",
            }
        ],
    )
    tool_message = ToolMessage(
        content="done",
        tool_call_id="call-1",
        id="tool-1",
        status="success",
    )

    serialized_ai = serialize_message(ai_message)
    serialized_tool = serialize_message(tool_message)

    assert serialized_ai["id"] == "ai-1"
    assert serialized_ai["tool_calls"][0]["id"] == "call-1"
    assert serialized_tool["tool_call_id"] == "call-1"
    assert serialized_tool["status"] == "success"


def test_serialize_state_exposes_public_thread_id_only() -> None:
    snapshot = SimpleNamespace(
        values={"messages": [HumanMessage(content="hello", id="human-1")]},
        next=("agent",),
        tasks=(),
        metadata={"source": "loop"},
        config={
            "configurable": {
                "thread_id": "user-secret:public-thread",
                "checkpoint_ns": "",
                "checkpoint_id": "checkpoint-1",
            }
        },
        parent_config={
            "configurable": {
                "thread_id": "user-secret:public-thread",
                "checkpoint_id": "checkpoint-0",
            }
        },
    )

    state = serialize_state(snapshot, thread_id="public-thread")

    assert state["values"]["messages"][0]["content"] == "hello"
    assert state["next"] == ["agent"]
    assert state["checkpoint"]["thread_id"] == "public-thread"
    assert state["checkpoint"]["checkpoint_id"] == "checkpoint-1"
    assert state["parent_checkpoint"]["thread_id"] == "public-thread"
    assert "user-secret" not in str(state)
