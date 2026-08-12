import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.infra.database import AsyncSessionLocal
from app.modules.chat import api as api_module
from app.modules.chat.executor import AgentExecutionResult
from app.modules.chat.service import ChatService
from app.modules.conversation.model import Message, MessageRole
from app.modules.request_run.model import RequestRun, RequestRunStatus
from app.modules.user.service import UserService


class CallbackExecutor:
    def __init__(
        self,
        *,
        callback: Callable[[uuid.UUID], Awaitable[None]] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.callback = callback
        self.error = error

    async def execute(
        self,
        *,
        request_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message: str,
        deadline_at: object,
    ) -> AgentExecutionResult:
        del conversation_id, message, deadline_at
        if self.callback is not None:
            await self.callback(request_id)
        if self.error is not None:
            raise self.error
        return AgentExecutionResult(content="durable final")


async def _create_conversation(
    client: AsyncClient, headers: dict[str, str], title: str
) -> uuid.UUID:
    response = await client.post(
        f"{settings.API_V1_STR}/conversations/",
        headers=headers,
        json={"title": title},
    )
    assert response.status_code == 200
    return uuid.UUID(response.json()["id"])


async def _message_roles(db: AsyncSession, request_id: uuid.UUID) -> list[MessageRole]:
    roles = (
        (
            await db.execute(
                select(Message.role)
                .where(Message.request_id == request_id)
                .order_by(Message.seq)
            )
        )
        .scalars()
        .all()
    )
    return list(roles)


async def test_assistant_commit_failure_cannot_leave_false_completed(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    conversation_id = await _create_conversation(
        client, normal_user_token_headers, "Final commit failure"
    )
    original_commit = AsyncSession.commit
    commit_count = 0

    async def fail_second_commit(session: AsyncSession) -> None:
        nonlocal commit_count
        commit_count += 1
        if commit_count == 2:
            raise RuntimeError("forced final commit failure")
        await original_commit(session)

    with monkeypatch.context() as scoped:
        scoped.setattr(
            api_module,
            "get_agent_executor",
            lambda: CallbackExecutor(),
        )
        scoped.setattr(AsyncSession, "commit", fail_second_commit)
        response = await client.post(
            f"{settings.API_V1_STR}/chat",
            headers={
                **normal_user_token_headers,
                "Idempotency-Key": "final-commit-failure",
            },
            json={
                "conversation_id": str(conversation_id),
                "message": "hello",
            },
        )

    assert response.status_code == 500
    assert "forced final commit failure" not in response.text
    request_id = uuid.UUID(response.json()["request_id"])
    request_run = await db.get(RequestRun, request_id)
    assert request_run is not None
    assert request_run.status is RequestRunStatus.FAILED
    assert request_run.error_code == "INTERNAL_ERROR"
    assert await _message_roles(db, request_id) == [MessageRole.USER]


async def test_cancel_wins_over_assistant_final_race(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    conversation_id = await _create_conversation(
        client, normal_user_token_headers, "Cancel race"
    )
    captured: dict[str, str] = {}

    async def cancel_running_request(request_id: uuid.UUID) -> None:
        captured["request_id"] = str(request_id)
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(RequestRun)
                .where(
                    RequestRun.id == request_id,
                    RequestRun.status == RequestRunStatus.RUNNING,
                )
                .values(
                    status=RequestRunStatus.CANCELLED,
                    finished_at=datetime.now(UTC),
                )
            )
            await session.commit()

    monkeypatch.setattr(
        api_module,
        "get_agent_executor",
        lambda: CallbackExecutor(callback=cancel_running_request),
    )
    response = await client.post(
        f"{settings.API_V1_STR}/chat",
        headers={
            **normal_user_token_headers,
            "Idempotency-Key": "cancel-final-race",
        },
        json={
            "conversation_id": str(conversation_id),
            "message": "hello",
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "REQUEST_CANCELLED"
    request_id = uuid.UUID(response.json()["request_id"])
    request_run = await db.get(RequestRun, request_id)
    assert request_run is not None
    assert request_run.status is RequestRunStatus.CANCELLED
    assert request_run.error_code is None
    assert await _message_roles(db, request_id) == [MessageRole.USER]


async def test_task_cancellation_marks_request_cancelled(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    conversation_id = await _create_conversation(
        client, normal_user_token_headers, "Task cancellation"
    )
    user = await UserService(db).get_by_email(settings.EMAIL_TEST_USER)
    assert user is not None
    request_id = uuid.uuid4()
    monkeypatch.setattr(
        api_module,
        "get_agent_executor",
        lambda: CallbackExecutor(error=asyncio.CancelledError()),
    )

    service = ChatService(db, executor=CallbackExecutor(error=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await service.chat(
            request_id=request_id,
            user_id=user.id,
            conversation_id=conversation_id,
            idempotency_key="task-cancelled",
            message="hello",
        )

    request_run = await db.get(RequestRun, request_id)
    assert request_run is not None
    await db.refresh(request_run)
    assert request_run.status is RequestRunStatus.CANCELLED
    assert request_run.finished_at is not None
    assert request_run.error_code is None
    assert await _message_roles(db, request_id) == [MessageRole.USER]
