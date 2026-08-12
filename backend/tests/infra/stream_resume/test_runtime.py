from __future__ import annotations

import asyncio

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
    await original.aclose()
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
