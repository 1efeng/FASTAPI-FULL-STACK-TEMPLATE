from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RunHandle:
    """Process-local transport handle.

    This is intentionally not a runtime state store. LangGraph owns checkpoints,
    messages and execution state.
    """

    thread_id: str
    task: asyncio.Task[Any]


class RunRegistry:
    """Minimal transport cancellation registry.

    The registry only knows how to locate the currently running asyncio task in
    this process. Durable recovery is provided by LangGraph checkpointing.
    """

    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], RunHandle] = {}

    def register(
        self,
        user_id: str,
        thread_id: str,
        run_id: str,
        task: asyncio.Task[Any],
    ) -> None:
        self._runs[(user_id, run_id)] = RunHandle(thread_id=thread_id, task=task)

    def get(
        self,
        user_id: str,
        run_id: str,
    ) -> RunHandle | None:
        return self._runs.get((user_id, run_id))

    def remove(self, user_id: str, run_id: str) -> None:
        self._runs.pop((user_id, run_id), None)


run_registry = RunRegistry()
