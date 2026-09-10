import asyncio
import json

import pytest

from app.chat.protocol.session import AgentStreamSession


def parse_event(frame: str) -> dict:
    line = next(line for line in frame.splitlines() if line.startswith("data:"))
    return json.loads(line.removeprefix("data: "))


@pytest.mark.asyncio
async def test_replay_from_last_event_id() -> None:
    session = AgentStreamSession("thread-1")

    await session.publish({"type": "one"})
    await session.publish({"type": "two"})
    await session.publish({"type": "three"})

    stream = session.subscribe(2)
    try:
        event = parse_event(await anext(stream))
        assert event["seq"] == 3
        assert event["data"]["type"] == "three"
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_disconnect_does_not_cancel_transport_session() -> None:
    session = AgentStreamSession("thread-1")

    stream = session.subscribe()
    await session.publish({"type": "running"})
    await anext(stream)
    await stream.aclose()

    await session.publish({"type": "completed"})

    replay = session.subscribe(1)
    try:
        event = parse_event(await anext(replay))
        assert event["data"]["type"] == "completed"
    finally:
        await replay.aclose()


@pytest.mark.asyncio
async def test_event_buffer_is_bounded() -> None:
    session = AgentStreamSession("thread-1")

    for index in range(1100):
        await session.publish({"index": index})

    stream = session.subscribe()
    try:
        first = parse_event(await anext(stream))
        assert first["seq"] == 101
    finally:
        await stream.aclose()
