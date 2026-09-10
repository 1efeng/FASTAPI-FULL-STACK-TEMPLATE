"""Convert LangGraph/LangChain events to Agent Streaming Protocol events."""

from __future__ import annotations

import time
from typing import Any

from fastapi.encoders import jsonable_encoder
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.messages.utils import convert_to_messages

from app.chat.protocol.events import ProtocolEvent, StreamEventType


class AgentEventAdapter:
    """Stateful adapter for one agent run's message and tool events."""

    def __init__(self) -> None:
        self._model_streams: dict[str, dict[str, str]] = {}
        self._tool_call_ids: dict[str, str] = {}

    def adapt(self, event: dict[str, Any]) -> list[ProtocolEvent]:
        event_name = event.get("event")
        event_run_id = str(event.get("run_id") or "")
        raw_data = event.get("data")
        data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
        node = _event_node(event)

        if event_name == "on_chat_model_stream":
            chunk = data.get("chunk")
            text = _message_text(chunk)
            if not text:
                return []

            stream_key = event_run_id or str(getattr(chunk, "id", None) or node or "model")
            stream_state = self._model_streams.get(stream_key)
            events: list[ProtocolEvent] = []
            if stream_state is None:
                message_id = str(getattr(chunk, "id", None) or f"ai-{stream_key}")
                stream_state = {"id": message_id, "text": ""}
                self._model_streams[stream_key] = stream_state
                events.extend(
                    [
                        ProtocolEvent(
                            StreamEventType.MESSAGE_DELTA,
                            "messages",
                            {"event": "message-start", "role": "ai", "id": message_id},
                            node,
                        ),
                        ProtocolEvent(
                            StreamEventType.MESSAGE_DELTA,
                            "messages",
                            {
                                "event": "content-block-start",
                                "index": 0,
                                "content": {"type": "text", "text": ""},
                            },
                            node,
                        ),
                    ]
                )
            stream_state["text"] += text
            events.append(
                ProtocolEvent(
                    StreamEventType.MESSAGE_DELTA,
                    "messages",
                    {
                        "event": "content-block-delta",
                        "index": 0,
                        "delta": {"type": "text-delta", "text": text},
                    },
                    node,
                )
            )
            return events

        if event_name == "on_chat_model_end":
            stream_key = event_run_id or str(node or "model")
            stream_state = self._model_streams.pop(stream_key, None)
            if stream_state is None:
                return []
            return [
                ProtocolEvent(
                    StreamEventType.MESSAGE_DELTA,
                    "messages",
                    {
                        "event": "content-block-finish",
                        "index": 0,
                        "content": {"type": "text", "text": stream_state["text"]},
                    },
                    node,
                ),
                ProtocolEvent(
                    StreamEventType.MESSAGE_DELTA,
                    "messages",
                    {"event": "message-finish"},
                    node,
                ),
            ]

        if event_name == "on_tool_start":
            raw_metadata = event.get("metadata")
            metadata: dict[str, Any] = (
                raw_metadata if isinstance(raw_metadata, dict) else {}
            )
            tool_call_id = str(metadata.get("tool_call_id") or event_run_id)
            self._tool_call_ids[event_run_id] = tool_call_id
            return [
                ProtocolEvent(
                    StreamEventType.TOOL_STARTED,
                    "tools",
                    {
                        "event": "tool-started",
                        "tool_call_id": tool_call_id,
                        "tool_name": str(event.get("name") or "tool"),
                        "input": jsonable(data.get("input")),
                    },
                    node,
                )
            ]

        if event_name == "on_tool_end":
            tool_call_id = self._tool_call_ids.pop(event_run_id, event_run_id)
            return [
                ProtocolEvent(
                    StreamEventType.TOOL_COMPLETED,
                    "tools",
                    {
                        "event": "tool-finished",
                        "tool_call_id": tool_call_id,
                        "output": jsonable(data.get("output")),
                    },
                    node,
                )
            ]

        if event_name == "on_tool_error":
            tool_call_id = self._tool_call_ids.pop(event_run_id, event_run_id)
            return [
                ProtocolEvent(
                    StreamEventType.RUN_FAILED,
                    "tools",
                    {
                        "event": "tool-error",
                        "tool_call_id": tool_call_id,
                        "message": str(data.get("error") or "Tool execution failed"),
                    },
                    node,
                )
            ]

        return []


def protocol_message(event: ProtocolEvent) -> dict[str, Any]:
    """Convert one normalized event into the Agent Streaming Protocol envelope.

    Sequence numbers and event ids are intentionally added by AgentStreamSession;
    this function only owns protocol conversion. The current graph is root-only,
    so its protocol namespace is the root namespace (`[]`).
    """
    return {
        "method": event.method,
        "params": {
            "namespace": [],
            "timestamp": int(time.time() * 1000),
            "data": jsonable(event.data),
        },
    }


def run_started(run_id: str) -> tuple[ProtocolEvent, ProtocolEvent]:
    base = {"graph_name": "agent", "run_id": run_id}
    return (
        ProtocolEvent(
            StreamEventType.RUN_STARTED,
            "lifecycle",
            {"event": "started", **base},
        ),
        ProtocolEvent(
            StreamEventType.RUN_STARTED,
            "lifecycle",
            {"event": "running", **base},
        ),
    )


def run_completed(run_id: str) -> ProtocolEvent:
    return ProtocolEvent(
        StreamEventType.RUN_COMPLETED,
        "lifecycle",
        {"event": "completed", "graph_name": "agent", "run_id": run_id},
    )


def run_interrupted(run_id: str) -> ProtocolEvent:
    return ProtocolEvent(
        StreamEventType.RUN_FAILED,
        "lifecycle",
        {"event": "interrupted", "graph_name": "agent", "run_id": run_id},
    )


def run_failed(run_id: str, error: Exception) -> ProtocolEvent:
    return ProtocolEvent(
        StreamEventType.RUN_FAILED,
        "lifecycle",
        {
            "event": "failed",
            "graph_name": "agent",
            "run_id": run_id,
            "error": str(error),
        },
    )


def input_messages(payload: Any) -> list[BaseMessage]:
    if not isinstance(payload, dict):
        raise ValueError("run.start input must be an object")
    raw_messages = payload.get("messages")
    if raw_messages is None:
        return []
    if not isinstance(raw_messages, list):
        raise ValueError("run.start input.messages must be an array")
    return list(convert_to_messages(raw_messages))


def serialize_message(message: BaseMessage) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": message.type,
        "content": jsonable(message.content),
    }
    if message.id:
        result["id"] = message.id
    if message.name:
        result["name"] = message.name
    if isinstance(message, AIMessage) and message.tool_calls:
        result["tool_calls"] = jsonable(message.tool_calls)
    if isinstance(message, ToolMessage):
        result["tool_call_id"] = message.tool_call_id
        if message.status:
            result["status"] = message.status
    return result


def serialize_state(snapshot: Any, *, thread_id: str) -> dict[str, Any]:
    """Serialize a LangGraph StateSnapshot for the frontend protocol."""
    raw_values = snapshot.values if isinstance(snapshot.values, dict) else {}
    values = dict(raw_values)
    raw_messages = values.get("messages")
    if isinstance(raw_messages, list):
        values["messages"] = [
            serialize_message(message) if isinstance(message, BaseMessage) else jsonable(message)
            for message in raw_messages
        ]

    return {
        "values": jsonable(values),
        "next": list(snapshot.next),
        "tasks": jsonable(list(snapshot.tasks)),
        "metadata": jsonable(snapshot.metadata),
        "checkpoint": _public_checkpoint(snapshot.config, thread_id=thread_id),
        "parent_checkpoint": _public_checkpoint(
            snapshot.parent_config,
            thread_id=thread_id,
        ),
    }


def jsonable(value: Any) -> Any:
    if isinstance(value, BaseMessage):
        return serialize_message(value)
    try:
        return jsonable_encoder(value)
    except (TypeError, ValueError):
        return str(value)


def _event_node(event: dict[str, Any]) -> str | None:
    metadata = event.get("metadata")
    if isinstance(metadata, dict):
        node = metadata.get("langgraph_node")
        if isinstance(node, str):
            return node
    name = event.get("name")
    return str(name) if isinstance(name, str) else None


def _message_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, str):
                chunks.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)
    return ""


def _public_checkpoint(config: Any, *, thread_id: str) -> dict[str, Any] | None:
    if not isinstance(config, dict):
        return None
    configurable = config.get("configurable")
    if not isinstance(configurable, dict):
        return None
    checkpoint: dict[str, Any] = {"thread_id": thread_id}
    for key in ("checkpoint_ns", "checkpoint_id"):
        value = configurable.get(key)
        if value is not None:
            checkpoint[key] = jsonable(value)
    return checkpoint
