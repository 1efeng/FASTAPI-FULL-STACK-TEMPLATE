import asyncio
import uuid
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from langchain_core.messages import AIMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.chat import service as service_module
from app.modules.conversation.model import Message
from app.modules.request_run.model import RequestRun, RequestRunStatus


class CountingAgent:
    def __init__(
        self,
        counter: list[int],
        *,
        entered: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        self.counter = counter
        self.entered = entered
        self.release = release

    async def ainvoke(self, *_: Any, **__: Any) -> dict[str, list[AIMessage]]:
        self.counter[0] += 1
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        return {"messages": [AIMessage(content="idempotent answer")]}


async def _create_conversation(
    client: AsyncClient,
    headers: dict[str, str],
    title: str,
) -> uuid.UUID:
    response = await client.post(
        f"{settings.API_V1_STR}/conversations/",
        headers=headers,
        json={"title": title},
    )
    assert response.status_code == 200
    return uuid.UUID(response.json()["id"])


async def _post_chat(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    conversation_id: uuid.UUID,
    key: str,
    message: str,
):
    return await client.post(
        f"{settings.API_V1_STR}/chat",
        headers={**headers, "Idempotency-Key": key},
        json={
            "conversation_id": str(conversation_id),
            "message": message,
        },
    )


async def test_completed_idempotency_replay_has_no_duplicate_cost(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    conversation_id = await _create_conversation(
        client,
        normal_user_token_headers,
        "Completed replay",
    )
    calls = [0]
    monkeypatch.setattr(
        service_module,
        "build_travel_agent",
        lambda **_: CountingAgent(calls),
    )

    first = await _post_chat(
        client,
        normal_user_token_headers,
        conversation_id=conversation_id,
        key="completed-replay",
        message="same payload",
    )
    replay = await _post_chat(
        client,
        normal_user_token_headers,
        conversation_id=conversation_id,
        key="completed-replay",
        message="same payload",
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == {
        "request_id": first.json()["request_id"],
        "content": "idempotent answer",
        "status": "completed",
        "error_code": None,
        "replayed": True,
    }
    assert calls == [1]
    request_count = (
        await db.execute(
            select(func.count())
            .select_from(RequestRun)
            .where(RequestRun.conversation_id == conversation_id)
        )
    ).scalar_one()
    message_count = (
        await db.execute(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == conversation_id)
        )
    ).scalar_one()
    assert request_count == 1
    assert message_count == 2


async def test_running_idempotency_replay_returns_existing_request(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await _create_conversation(
        client,
        normal_user_token_headers,
        "Running replay",
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = [0]
    monkeypatch.setattr(
        service_module,
        "build_travel_agent",
        lambda **_: CountingAgent(calls, entered=entered, release=release),
    )

    first_task = asyncio.create_task(
        _post_chat(
            client,
            normal_user_token_headers,
            conversation_id=conversation_id,
            key="running-replay",
            message="same payload",
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=2)
    replay = await _post_chat(
        client,
        normal_user_token_headers,
        conversation_id=conversation_id,
        key="running-replay",
        message="same payload",
    )

    assert replay.status_code == 202
    assert replay.json()["status"] == "running"
    assert replay.json()["content"] is None
    assert replay.json()["replayed"] is True
    assert calls == [1]

    release.set()
    first = await asyncio.wait_for(first_task, timeout=2)
    assert first.status_code == 200
    assert first.json()["request_id"] == replay.json()["request_id"]
    assert calls == [1]


async def test_concurrent_idempotency_race_executes_agent_once(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await _create_conversation(
        client,
        normal_user_token_headers,
        "Concurrent replay race",
    )
    calls = [0]
    arrivals = 0
    both_arrived = asyncio.Event()
    original_lookup = service_module.RequestRunRepository.get_by_user_idempotency

    async def synchronized_lookup(
        repository: service_module.RequestRunRepository,
        user_id: uuid.UUID,
        idempotency_key: str,
    ) -> RequestRun | None:
        nonlocal arrivals
        if arrivals < 2:
            arrivals += 1
            if arrivals == 2:
                both_arrived.set()
            await asyncio.wait_for(both_arrived.wait(), timeout=2)
        return await original_lookup(repository, user_id, idempotency_key)

    monkeypatch.setattr(
        service_module.RequestRunRepository,
        "get_by_user_idempotency",
        synchronized_lookup,
    )
    monkeypatch.setattr(
        service_module,
        "build_travel_agent",
        lambda **_: CountingAgent(calls),
    )

    first, second = await asyncio.gather(
        _post_chat(
            client,
            normal_user_token_headers,
            conversation_id=conversation_id,
            key="concurrent-race",
            message="same payload",
        ),
        _post_chat(
            client,
            normal_user_token_headers,
            conversation_id=conversation_id,
            key="concurrent-race",
            message="same payload",
        ),
    )

    assert {first.status_code, second.status_code}.issubset({200, 202})
    assert first.json()["request_id"] == second.json()["request_id"]
    assert first.json()["replayed"] is not second.json()["replayed"]
    assert calls == [1]


async def test_reusing_idempotency_key_for_different_payload_is_rejected(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await _create_conversation(
        client,
        normal_user_token_headers,
        "Mismatched replay",
    )
    calls = [0]
    monkeypatch.setattr(
        service_module,
        "build_travel_agent",
        lambda **_: CountingAgent(calls),
    )
    first = await _post_chat(
        client,
        normal_user_token_headers,
        conversation_id=conversation_id,
        key="mismatched-replay",
        message="first payload",
    )
    replay = await _post_chat(
        client,
        normal_user_token_headers,
        conversation_id=conversation_id,
        key="mismatched-replay",
        message="different payload",
    )

    assert first.status_code == 200
    assert replay.status_code == 409
    assert replay.json()["code"] == "DUPLICATE_REQUEST"
    assert replay.json()["request_id"] == first.json()["request_id"]
    assert calls == [1]


async def test_explicit_cancel_is_owned_and_stops_agent(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    conversation_id = await _create_conversation(
        client,
        normal_user_token_headers,
        "Explicit cancellation",
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = [0]
    monkeypatch.setattr(
        service_module,
        "build_travel_agent",
        lambda **_: CountingAgent(calls, entered=entered, release=release),
    )
    chat_task = asyncio.create_task(
        _post_chat(
            client,
            normal_user_token_headers,
            conversation_id=conversation_id,
            key="explicit-cancel",
            message="cancel me",
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=2)
    request_run = (
        await db.execute(
            select(RequestRun).where(RequestRun.idempotency_key == "explicit-cancel")
        )
    ).scalar_one()

    hidden = await client.post(
        f"{settings.API_V1_STR}/chat/requests/{request_run.id}/cancel",
        headers=superuser_token_headers,
    )
    assert hidden.status_code == 404

    cancelled = await client.post(
        f"{settings.API_V1_STR}/chat/requests/{request_run.id}/cancel",
        headers=normal_user_token_headers,
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    chat_response = await asyncio.wait_for(chat_task, timeout=2)
    assert chat_response.status_code == 409
    assert chat_response.json()["code"] == "REQUEST_CANCELLED"
    await db.refresh(request_run)
    assert request_run.status is RequestRunStatus.CANCELLED
    assert request_run.finished_at is not None
    assert calls == [1]


async def test_absolute_deadline_marks_request_failed(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    conversation_id = await _create_conversation(
        client,
        normal_user_token_headers,
        "Absolute deadline",
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = [0]
    monkeypatch.setattr(settings, "REQUEST_DEADLINE_SECONDS", 0.05)
    monkeypatch.setattr(
        service_module,
        "build_travel_agent",
        lambda **_: CountingAgent(calls, entered=entered, release=release),
    )

    response = await _post_chat(
        client,
        normal_user_token_headers,
        conversation_id=conversation_id,
        key="absolute-deadline",
        message="wait forever",
    )

    assert response.status_code == 504
    assert response.json()["code"] == "REQUEST_DEADLINE_EXCEEDED"
    request_run = await db.get(RequestRun, uuid.UUID(response.json()["request_id"]))
    assert request_run is not None
    assert request_run.status is RequestRunStatus.FAILED
    assert request_run.error_code == "REQUEST_DEADLINE_EXCEEDED"
    assert request_run.deadline_at - request_run.started_at == timedelta(seconds=0.05)
    assert calls == [1]
