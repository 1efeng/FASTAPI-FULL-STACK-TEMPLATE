"""Agent streaming protocol events.

This module only defines transport-level events. It does not own runtime,
engine, scheduler, or durable execution behavior.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class StreamEventType(StrEnum):
    RUN_STARTED = "run.started"
    MESSAGE_DELTA = "message.delta"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"


@dataclass(frozen=True, slots=True)
class ProtocolEvent:
    """One normalized event ready for the Agent Streaming Protocol wire."""

    kind: StreamEventType
    method: str
    data: Any
    node: str | None = None
