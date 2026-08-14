import asyncio
import uuid

import pytest

from app.modules.chat.execution import ExecutionSupervisor


async def test_supervisor_owns_execution_task_and_product_cancel_stops_it() -> None:
    supervisor = ExecutionSupervisor()
    request_id = uuid.uuid4()
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def execution() -> None:
        entered.set()
        try:
            await asyncio.Future[None]()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = supervisor.start(request_id, execution())
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert supervisor.is_running(request_id)
    assert supervisor.cancel_signal(request_id) is not None

    supervisor.request_cancel(request_id)
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0)
    assert cancelled.is_set()
    assert not supervisor.is_running(request_id)
    with pytest.raises(RuntimeError, match="Unknown execution"):
        supervisor.cancel_signal(request_id)


async def test_supervisor_shutdown_bounded_drain_clears_registry() -> None:
    supervisor = ExecutionSupervisor()
    request_id = uuid.uuid4()

    async def execution() -> None:
        await asyncio.Future[None]()

    supervisor.start(request_id, execution())
    assert supervisor.is_running(request_id)

    await supervisor.shutdown(grace_seconds=1)
    assert not supervisor.is_running(request_id)


async def test_cancel_before_start_fences_late_execution() -> None:
    supervisor = ExecutionSupervisor()
    request_id = uuid.uuid4()
    entered = asyncio.Event()

    supervisor.request_cancel(request_id)

    async def execution() -> None:
        entered.set()
        await asyncio.Future[None]()

    task = supervisor.start(request_id, execution())
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not entered.is_set()
