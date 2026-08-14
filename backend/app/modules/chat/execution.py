"""In-process execution supervision.

``ExecutionSupervisor`` owns the *execution* lifetime of an agent request
(request_id → asyncio.Task, cancellation, deadline), decoupled from the HTTP
subscriber lifetime. It does NOT own Product RequestRun SOT, idempotency, or the
stream pump (that is StreamResumeStore's job).

This is the P0-3 task-topology owner: Agent task != stream pump task.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Coroutine
from typing import Any, TypeVar

logger = logging.getLogger(__name__)
ExecutionResult = TypeVar("ExecutionResult")


class ExecutionSupervisor:
    """In-process registry of running agent executions.

    Not crash-durable: tasks live in this process's event loop. A process crash
    loses them; Product RequestRun reconciliation is the recovery path (future
    DBOS provides execution durability).
    """

    def __init__(self) -> None:
        self._tasks: dict[uuid.UUID, asyncio.Task[Any]] = {}
        self._cancel_handles: dict[uuid.UUID, asyncio.Event] = {}
        self._pending_cancellations: set[uuid.UUID] = set()

    def start(
        self,
        request_id: uuid.UUID,
        coro: Coroutine[Any, Any, ExecutionResult],
    ) -> asyncio.Task[ExecutionResult]:
        """Register and start an execution coroutine under ``request_id``."""
        if request_id in self._tasks:
            raise RuntimeError(f"Execution already registered: {request_id}")

        cancel_event = asyncio.Event()
        self._cancel_handles[request_id] = cancel_event
        pre_cancelled = request_id in self._pending_cancellations
        if pre_cancelled:
            cancel_event.set()

        task = asyncio.create_task(coro, name=f"execution:{request_id}")
        self._tasks[request_id] = task
        if pre_cancelled:
            task.cancel()
        task.add_done_callback(lambda _: self._forget(request_id))
        return task

    def _forget(self, request_id: uuid.UUID) -> None:
        self._tasks.pop(request_id, None)
        self._cancel_handles.pop(request_id, None)
        self._pending_cancellations.discard(request_id)

    def is_running(self, request_id: uuid.UUID) -> bool:
        task = self._tasks.get(request_id)
        return task is not None and not task.done()

    def cancel_signal(self, request_id: uuid.UUID) -> asyncio.Event:
        """Return the cancellation event for ``request_id``.

        The execution coroutine awaits this event to learn of Product cancellation.
        """
        event = self._cancel_handles.get(request_id)
        if event is None:
            raise RuntimeError(f"Unknown execution: {request_id}")
        return event

    def cancellation_requested(self, request_id: uuid.UUID) -> bool:
        event = self._cancel_handles.get(request_id)
        return event is not None and event.is_set()

    def request_cancel(self, request_id: uuid.UUID) -> None:
        """Signal Product cancellation to the execution coroutine."""
        event = self._cancel_handles.get(request_id)
        if event is not None:
            event.set()
        else:
            self._pending_cancellations.add(request_id)
        task = self._tasks.get(request_id)
        if task is not None and not task.done():
            task.cancel()

    async def shutdown(self, *, grace_seconds: float = 5.0) -> None:
        """Cancel all running executions (bounded drain), then await them."""
        tasks = [t for t in self._tasks.values() if not t.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=grace_seconds)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._cancel_handles.clear()
        self._pending_cancellations.clear()


_supervisor: ExecutionSupervisor | None = None


def get_execution_supervisor() -> ExecutionSupervisor:
    global _supervisor
    if _supervisor is None:
        _supervisor = ExecutionSupervisor()
    return _supervisor
