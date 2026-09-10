"""Agent streaming protocol events.

This module only defines transport-level events. It does not own runtime,
engine, scheduler, or durable execution behavior.
"""

from enum import StrEnum


class StreamEventType(StrEnum):
    RUN_STARTED = "run.started"
    MESSAGE_DELTA = "message.delta"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
