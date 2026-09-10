import json

import pytest

from app.chat.protocol.session import AgentStreamSession


def parse_event(frame: str) -> dict:
    line = next(line for line in frame.splitlines() if line.startswith("data:"))
    return json.loads(line.removeprefix("data: "))


def parse_event_id(frame: str) -> int:
    line = next(line for line in frame.splitlines() if line.startswith("id:"))
    return int(line.removeprefix("id: ").strip())


def protocol_event(marker: str) -> dict:
    return {
        "method": "lifecycle",
        "params": {
            "namespace": [],
            "timestamp": 1,
            "data": {"marker": marker},
        },
    }


@pytest.mark.asyncio
async def test_replay_from_last_event_id() -> None:
    session = AgentStreamSession("thread-1")

    await session.publish(protocol_event("one"))
    await session.publish(protocol_event("two"))
    await session.publish(protocol_event("three"))

    stream = session.subscribe(2)
    try:
        frame = await anext(stream)
        event = parse_event(frame)
        assert parse_event_id(frame) == 3
        assert event["method"] == "lifecycle"
        assert event["params"]["data"]["marker"] == "three"
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_disconnect_does_not_cancel_transport_session() -> None:
    session = AgentStreamSession("thread-1")

    stream = session.subscribe()
    await session.publish(protocol_event("running"))
    await anext(stream)
    await stream.aclose()

    await session.publish(protocol_event("completed"))

    replay = session.subscribe(1)
    try:
        event = parse_event(await anext(replay))
        assert event["params"]["data"]["marker"] == "completed"
    finally:
        await replay.aclose()


@pytest.mark.asyncio
async def test_event_buffer_is_bounded() -> None:
    session = AgentStreamSession("thread-1")

    for index in range(1100):
        await session.publish(protocol_event(str(index)))

    stream = session.subscribe()
    try:
        frame = await anext(stream)
        first = parse_event(frame)
        assert parse_event_id(frame) == 101
        assert first["params"]["data"]["marker"] == "100"
    finally:
        await stream.aclose()
