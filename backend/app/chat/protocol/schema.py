"""HTTP request schemas for the Agent Streaming Protocol boundary."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StreamOptions(BaseModel):
    """Options forwarded when creating a LangGraph stream."""

    channels: list[str] = Field(default_factory=list)
    namespaces: list[list[str]] | None = None
    depth: int | None = None


class RunStartParams(BaseModel):
    """Payload for run.start command.

    Input is the graph input. Stream options control the protocol stream and
    must not become part of graph state.
    """

    model_config = ConfigDict(extra="allow")

    input: Any | None = None
    stream: StreamOptions | None = None


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    method: str
    params: dict[str, Any]


class StreamRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    channels: list[str] = Field(default_factory=list)
    namespaces: list[list[str]] | None = None
    depth: int | None = None
    since: int | None = None
    last_event_id: int | None = None
