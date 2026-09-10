from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RunHandle:
    """Process-local transport handle.

    LangGraph owns checkpoints, messages and execution state. This registry only
    prevents duplicate transport runs and locates active asyncio tasks.
    """

    thread_id: str
    command_id: int
    task: asyncio.Task[Any]


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[tuple[str, str], RunHandle] = {}
        self._commands: dict[tuple[str, str, int], str] = {}

    def register(
        self,
        user_id: str,
        thread_id: str,
        run_id: str,
        command_id: int,
        task: asyncio.Task[Any],
    ) -> None:
        self._runs[(user_id, run_id)] = RunHandle(
            thread_id=thread_id,
            command_id=command_id,
            task=task,
        )
        self._commands[(user_id, thread_id, command_id)] = run_id

    def find_command(
        self,
        user_id: str,
        thread_id: str,
        command_id: int,
    ) -> str | None:
        return self._commands.get((user_id, thread_id, command_id))

    def get(self, user_id: str, run_id: str) -> RunHandle | None:
        return self._runs.get((user_id, run_id))

    def cancel_transport(self, user_id: str, run_id: str) -> bool:
        """Cancel only the local transport task.

        This intentionally does not represent a LangGraph interrupt. Durable
        interruption/resume must go through LangGraph checkpoint APIs.
        """
        handle = self.get(user_id, run_id)
        if not handle:
            return False
        handle.task.cancel()
        return True

    def remove(self, user_id: str, run_id: str) -> None:
        handle = self._runs.pop((user_id, run_id), None)
        if handle:
            self._commands.pop(
                (user_id, handle.thread_id, handle.command_id),
                None,
            )


run_registry = RunRegistry()
