from __future__ import annotations

import asyncio
from typing import Any


class RunRegistry:
    """Transport run task registry.

    This registry only tracks asyncio tasks created by the HTTP transport.
    It does not own LangGraph state, checkpoints, messages, or runtime state.
    """

    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], asyncio.Task[Any]] = {}

    def register(self, user_id: str, run_id: str, task: asyncio.Task[Any]) -> None:
        self._runs[(user_id, run_id)] = task

    def get(self, user_id: str, run_id: str) -> asyncio.Task[Any] | None:
        return self._runs.get((user_id, run_id))

    def remove(self, user_id: str, run_id: str) -> None:
        self._runs.pop((user_id, run_id), None)


run_registry = RunRegistry()
