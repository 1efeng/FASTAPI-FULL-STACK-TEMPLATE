from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage


def _collect_text(parts: list[dict[str, Any]]) -> str:
    """Collect text parts from an AI SDK UIMessage.

    Chapter 1 intentionally supports the complete text-chat subset only. Tool,
    reasoning, file, source and approval parts are ignored until their chapters
    introduce the corresponding runtime behavior.
    """
    return "".join(
        part.get("text") or ""
        for part in parts
        if part.get("type") == "text"
    )


def to_langchain_messages(ui_messages: list[dict[str, Any]]) -> list[BaseMessage]:
    """Convert AI SDK `UIMessage[]` into LangChain messages.

    The frontend keeps AI SDK's native request shape. This adapter is the only
    place that knows how that client-side protocol maps to LangChain.
    """
    messages: list[BaseMessage] = []

    for message in ui_messages:
        role = message.get("role")
        parts = message.get("parts") or []
        text = _collect_text(parts)

        if not text:
            continue

        if role == "user":
            messages.append(HumanMessage(content=text))
        elif role == "assistant":
            messages.append(AIMessage(content=text))
        elif role == "system":
            messages.append(SystemMessage(content=text))

    return messages
