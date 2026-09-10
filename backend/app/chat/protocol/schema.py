"""HTTP request schemas for the Agent Streaming Protocol boundary."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    method: str
    params: dict[str, Any]


class StreamRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    channels: list[str]
    namespaces: list[list[str]] | None = None
    depth: int | None = None
    since: int | None = None
