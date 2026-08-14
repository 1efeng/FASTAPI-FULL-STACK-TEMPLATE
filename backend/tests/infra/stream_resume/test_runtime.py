from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import cast

import pytest

from app.infra.stream_resume.errors import (
    StreamProducerFailed,
    StreamProducerInterrupted,
)
from app.infra.stream_resume.protocol import StreamState
from app.infra.stream_resume.runtime import ResumableStreamRuntime

from .memory_backend import MemoryBackend, MemoryBus


async def collect(stream):
    return "".join([chunk async for chunk in stream])


@pytest.mark.asyncio
async def test_normal_stream_finishes_done() -> None:
    runtime = ResumableStreamRuntime(MemoryBackend(MemoryBus()))

    async def producer():
        yield "A"
        yield "B"

    stream = await runtime.start("req-1", producer)
    assert stream is not None
    assert await collect(stream) == "AB"
    assert await runtime.status("req-1") is StreamState.DONE
    await runtime.close()


@pytest.mark.asyncio
async def test_resume_from_another_context_gets_backlog_and_live_data() -> None:
    bus = MemoryBus()
    owner = ResumableStreamRuntime(MemoryBackend(bus))
    replica = ResumableStreamRuntime(MemoryBackend(bus))
    release = asyncio.Event()

    async def producer():
        yield "A"
        await release.wait()
        yield "B"

    original = await owner.start("req-2", producer)
    assert original is not None

    original_first = await anext(original)
    assert original_first == "A"

    resumed = await replica.resume("req-2")
    assert resumed is not None
    resumed_first = await anext(resumed)
    assert resumed_first == "A"

    release.set()
    assert await collect(original) == "B"
    assert await collect(resumed) == "B"

    await replica.close()
    await owner.close()


@pytest.mark.asyncio
async def test_skip_characters_applies_to_replay_backlog() -> None:
    bus = MemoryBus()
    owner = ResumableStreamRuntime(MemoryBackend(bus))
    replica = ResumableStreamRuntime(MemoryBackend(bus))
    release = asyncio.Event()

    async def producer():
        yield "hello"
        await release.wait()
        yield " world"

    original = await owner.start("req-3", producer)
    assert original is not None
    assert await anext(original) == "hello"

    resumed = await replica.resume("req-3", skip_characters=2)
    assert resumed is not None
    assert await anext(resumed) == "llo"

    release.set()
    assert await collect(resumed) == " world"
    await cast(AsyncGenerator[str], original).aclose()
    await replica.close()
    await owner.close()


@pytest.mark.asyncio
async def test_concurrent_start_claims_only_one_producer() -> None:
    bus = MemoryBus()
    a = ResumableStreamRuntime(MemoryBackend(bus))
    b = ResumableStreamRuntime(MemoryBackend(bus))
    producer_calls = 0
    release = asyncio.Event()

    async def producer():
        nonlocal producer_calls
        producer_calls += 1
        await release.wait()
        yield "done"

    first, second = await asyncio.gather(
        a.start("same-request", producer),
        b.start("same-request", producer),
    )
    assert (first is None) != (second is None)
    await asyncio.sleep(0)
    assert producer_calls == 1
    release.set()
    winner = first if first is not None else second
    assert winner is not None
    assert await collect(winner) == "done"
    await a.close()
    await b.close()


@pytest.mark.asyncio
async def test_terminal_state_prevents_same_stream_from_restarting() -> None:
    bus = MemoryBus()
    first_runtime = ResumableStreamRuntime(MemoryBackend(bus))
    second_runtime = ResumableStreamRuntime(MemoryBackend(bus))
    producer_calls = 0

    async def producer():
        nonlocal producer_calls
        producer_calls += 1
        yield "done"

    first = await first_runtime.start("terminal-request", producer)
    assert first is not None
    assert await collect(first) == "done"
    assert await first_runtime.status("terminal-request") is StreamState.DONE

    second = await second_runtime.start("terminal-request", producer)
    assert second is None
    assert producer_calls == 1

    await second_runtime.close()
    await first_runtime.close()


@pytest.mark.asyncio
async def test_active_state_and_producer_lease_are_separate_keys() -> None:
    bus = MemoryBus()
    runtime = ResumableStreamRuntime(MemoryBackend(bus))
    release = asyncio.Event()

    async def producer():
        await release.wait()
        yield "done"

    stream = await runtime.start("separate-keys", producer)
    assert stream is not None
    assert bus.values[runtime._state_key("separate-keys")] == "ACTIVE"
    assert bus.values[runtime._lease_key("separate-keys")] != "ACTIVE"

    release.set()
    assert await collect(stream) == "done"
    await runtime.close()


@pytest.mark.asyncio
async def test_producer_failure_is_not_reported_as_done() -> None:
    runtime = ResumableStreamRuntime(MemoryBackend(MemoryBus()))

    async def producer():
        yield "before"
        raise ValueError("provider-secret-should-not-cross-transport")

    stream = await runtime.start("req-failed", producer)
    assert stream is not None
    assert await anext(stream) == "before"
    with pytest.raises(StreamProducerFailed) as exc_info:
        await anext(stream)
    assert exc_info.value.reason == "ValueError"
    assert "provider-secret" not in str(exc_info.value)
    assert await runtime.status("req-failed") is StreamState.FAILED
    await runtime.close()


@pytest.mark.asyncio
async def test_close_marks_active_producer_interrupted() -> None:
    bus = MemoryBus()
    runtime = ResumableStreamRuntime(MemoryBackend(bus))
    blocker = asyncio.Event()

    async def producer():
        yield "A"
        await blocker.wait()
        yield "B"

    stream = await runtime.start("req-interrupted", producer)
    assert stream is not None
    assert await anext(stream) == "A"
    await runtime.close(close_backend=False)
    assert await runtime.status("req-interrupted") is StreamState.INTERRUPTED

    with pytest.raises(StreamProducerInterrupted):
        await ResumableStreamRuntime(MemoryBackend(bus)).resume("req-interrupted")


@pytest.mark.asyncio
async def test_fenced_producer_does_not_overwrite_new_owner_state() -> None:
    """P0-1: a producer that lost its lease must not write terminal state.

    Simulate: A claims, then its lease is stolen by B (SET NX on the lease key).
    A must be fenced — its DONE write must not overwrite B's ACTIVE state.
    """
    bus = MemoryBus()
    backend_a = MemoryBackend(bus)
    backend_b = MemoryBackend(bus)
    a = ResumableStreamRuntime(backend_a)
    b = ResumableStreamRuntime(backend_b)
    release = asyncio.Event()

    async def producer_a():
        yield "A1"
        await release.wait()
        yield "A2"

    stream_a = await a.start("req-fence", producer_a)
    assert stream_a is not None
    assert await anext(stream_a) == "A1"

    # Steal the lease out from under A: overwrite the lease key directly (this
    # simulates TTL expiry + a new owner's SET NX winning, without going through
    # claim_lease which correctly refuses because the key still exists).
    async with bus.lock:
        bus.values[a._lease_key("req-fence")] = "stolen-token"

    # A's heartbeat will now fail compare-and-renew and fence A.
    # Release A so it tries to write DONE; it must be fenced and skip the write.
    release.set()
    await asyncio.sleep(0.1)

    # A's terminal write must NOT have overwritten the lease-holder's state.
    # (B has not started a producer here, but the lease belongs to "stolen-token",
    # so A's DONE/FAILED/INTERRUPTED write must be suppressed.)
    assert await a.status("req-fence") is not StreamState.DONE

    await a.close(close_backend=False)
    await b.close(close_backend=False)


@pytest.mark.asyncio
async def test_heartbeat_failure_fences_producer() -> None:
    """A heartbeat exception must fence the producer, not silently continue."""
    bus = MemoryBus()

    class FailingRenewBackend(MemoryBackend):
        fail_renew = False

        async def renew_lease(
            self, lease_key, state_key, token, *, ttl_seconds
        ):
            if self.fail_renew:
                raise RuntimeError("redis down")
            return await super().renew_lease(
                lease_key,
                state_key,
                token,
                ttl_seconds=ttl_seconds,
            )

    backend = FailingRenewBackend(bus)
    runtime = ResumableStreamRuntime(
        backend, heartbeat_interval_seconds=0.01
    )
    release = asyncio.Event()

    async def producer():
        yield "X"
        await release.wait()
        yield "Y"

    stream = await runtime.start("req-hb-fail", producer)
    assert stream is not None
    assert await anext(stream) == "X"

    # Heartbeat fails → fenced → producer stops publishing; terminal state not DONE.
    backend.fail_renew = True
    await asyncio.sleep(0.02)
    release.set()
    with pytest.raises(StreamProducerInterrupted):
        await anext(stream)
    assert await runtime.status("req-hb-fail") is not StreamState.DONE

    await runtime.close(close_backend=False)
