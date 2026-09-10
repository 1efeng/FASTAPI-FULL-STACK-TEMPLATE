"""Adapters between agent events and streaming protocol events.

Keep LangGraph/LangChain conversion isolated from HTTP transport.
"""

from typing import Any


async def adapt_agent_event(event: Any) -> dict[str, Any]:
    """Convert an agent event into a protocol event.

    Detailed provider/runtime mapping is added with the corresponding feature
    implementation. This boundary intentionally stays small.
    """
    return {"event": event}
