from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


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
    """Convert trusted text history from AI SDK `UIMessage[]` to LangChain.

    The frontend keeps AI SDK's native request shape. System instructions are
    deliberately not accepted from the browser; the server owns them in
    `chat/agent.py` through the runtime Skill.
    """
    messages: list[BaseMessage] = []

    for message in ui_messages:
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue

        parts = message.get("parts") or []
        text = _collect_text(parts)
        if not text:
            continue

        if role == "user":
            messages.append(HumanMessage(content=text))
        else:
            messages.append(AIMessage(content=text))

    return messages
