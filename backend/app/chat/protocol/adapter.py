"""Transport helpers for LangGraph native agent streaming protocol.

LangGraph owns runtime events (messages, updates, values, interrupts,
checkpoints). This module only handles the HTTP transport envelope.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi.encoders import jsonable_encoder
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.messages.utils import convert_to_messages



def protocol_message(data: Any) -> dict[str, Any]:
    """Wrap a LangGraph streaming payload for Agent Protocol transport."""
    return {
        "method": "stream.event",
        "params": {
            "namespace": [],
            "timestamp": int(time.time() * 1000),
            "data": jsonable(data),
        },
    }



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
    return result



def serialize_state(snapshot: Any, *, thread_id: str) -> dict[str, Any]:
    values = dict(snapshot.values) if isinstance(snapshot.values, dict) else {}
    messages = values.get("messages")
    if isinstance(messages, list):
        values["messages"] = [
            serialize_message(message) if isinstance(message, BaseMessage) else jsonable(message)
            for message in messages
        ]
    return {
        "values": jsonable(values),
        "next": list(snapshot.next),
        "tasks": jsonable(list(snapshot.tasks)),
        "metadata": jsonable(snapshot.metadata),
        "checkpoint": {"thread_id": thread_id},
    }



def jsonable(value: Any) -> Any:
    if isinstance(value, BaseMessage):
        return serialize_message(value)
    try:
        return jsonable_encoder(value)
    except (TypeError, ValueError):
        return str(value)
