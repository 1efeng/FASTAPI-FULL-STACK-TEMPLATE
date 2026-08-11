import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.model import Conversation, Message, MessageRole
from app.modules.request_run.model import RequestRun, RequestRunStatus
from app.modules.user.model import User
from tests.utils.user import create_random_user


async def _create_conversation(db: AsyncSession) -> tuple[User, Conversation]:
    user = await create_random_user(db)
    conversation = Conversation(user_id=user.id)
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return user, conversation


def _completed_run(
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    idempotency_key: str,
) -> RequestRun:
    now = datetime.now(UTC)
    return RequestRun(
        id=uuid.uuid4(),
        user_id=user_id,
        conversation_id=conversation_id,
        idempotency_key=idempotency_key,
        status=RequestRunStatus.COMPLETED,
        started_at=now,
        deadline_at=now + timedelta(seconds=30),
        finished_at=now,
    )


async def test_business_persistence_round_trip(db: AsyncSession) -> None:
    user, conversation = await _create_conversation(db)
    now = datetime.now(UTC)
    request_id = uuid.uuid4()
    request_run = RequestRun(
        id=request_id,
        user_id=user.id,
        conversation_id=conversation.id,
        idempotency_key="round-trip",
        status=RequestRunStatus.RUNNING,
        started_at=now,
        deadline_at=now + timedelta(seconds=30),
    )
    user_message = Message(
        conversation_id=conversation.id,
        request_id=request_id,
        role=MessageRole.USER,
        content="hello",
    )
    db.add(request_run)
    await db.flush()
    db.add(user_message)
    await db.commit()
    await db.refresh(request_run)
    await db.refresh(user_message)

    assert conversation.langgraph_thread_id != conversation.id
    assert request_run.id == user_message.request_id
    assert request_run.id == request_id
    assert request_run.status is RequestRunStatus.RUNNING
    assert user_message.seq > 0

    assistant_message = Message(
        conversation_id=conversation.id,
        request_id=request_run.id,
        role=MessageRole.ASSISTANT,
        content="hi",
    )
    request_run.status = RequestRunStatus.COMPLETED
    request_run.finished_at = datetime.now(UTC)
    db.add(assistant_message)
    await db.commit()

    messages = (
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.seq)
            )
        )
        .scalars()
        .all()
    )
    assert [message.role for message in messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert messages[0].seq < messages[1].seq


async def test_only_one_running_request_per_conversation(
    db: AsyncSession,
) -> None:
    user, conversation = await _create_conversation(db)
    now = datetime.now(UTC)
    first = RequestRun(
        user_id=user.id,
        conversation_id=conversation.id,
        idempotency_key="first",
        status=RequestRunStatus.RUNNING,
        started_at=now,
        deadline_at=now + timedelta(seconds=30),
    )
    db.add(first)
    await db.commit()

    second = RequestRun(
        user_id=user.id,
        conversation_id=conversation.id,
        idempotency_key="second",
        status=RequestRunStatus.RUNNING,
        started_at=now,
        deadline_at=now + timedelta(seconds=30),
    )
    db.add(second)
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_idempotency_key_is_unique_per_user(db: AsyncSession) -> None:
    user, first_conversation = await _create_conversation(db)
    second_conversation = Conversation(user_id=user.id)
    db.add(second_conversation)
    await db.commit()
    await db.refresh(second_conversation)

    first = _completed_run(
        user_id=user.id,
        conversation_id=first_conversation.id,
        idempotency_key="same-key",
    )
    db.add(first)
    await db.commit()

    duplicate = _completed_run(
        user_id=user.id,
        conversation_id=second_conversation.id,
        idempotency_key="same-key",
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()

    other_user, other_conversation = await _create_conversation(db)
    other_user_run = _completed_run(
        user_id=other_user.id,
        conversation_id=other_conversation.id,
        idempotency_key="same-key",
    )
    db.add(other_user_run)
    await db.commit()


async def test_request_role_is_unique_per_message(db: AsyncSession) -> None:
    user, conversation = await _create_conversation(db)
    request_run = _completed_run(
        user_id=user.id,
        conversation_id=conversation.id,
        idempotency_key="message-role",
    )
    first = Message(
        conversation_id=conversation.id,
        request_id=request_run.id,
        role=MessageRole.USER,
        content="first",
    )
    db.add(request_run)
    await db.flush()
    db.add(first)
    await db.commit()

    duplicate = Message(
        conversation_id=conversation.id,
        request_id=request_run.id,
        role=MessageRole.USER,
        content="duplicate",
    )
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_terminal_status_requires_finished_at(db: AsyncSession) -> None:
    user, conversation = await _create_conversation(db)
    now = datetime.now(UTC)
    invalid = RequestRun(
        user_id=user.id,
        conversation_id=conversation.id,
        idempotency_key="missing-finished-at",
        status=RequestRunStatus.FAILED,
        started_at=now,
        deadline_at=now + timedelta(seconds=30),
    )
    db.add(invalid)
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_schema_has_contract_indexes_and_constraints(
    db: AsyncSession,
) -> None:
    index_names = set(
        (
            await db.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND tablename IN ('conversation', 'request_run', 'message')
                    """
                )
            )
        )
        .scalars()
        .all()
    )
    constraint_names = set(
        (
            await db.execute(
                text(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid IN (
                        'conversation'::regclass,
                        'request_run'::regclass,
                        'message'::regclass
                    )
                    """
                )
            )
        )
        .scalars()
        .all()
    )

    assert {
        "ix_conversation_active_user_last_message",
        "ix_message_conversation_seq",
        "ix_request_run_conversation_created_at",
        "ix_request_run_running_deadline",
        "uq_request_run_one_running_per_conversation",
    } <= index_names
    assert {
        "ck_message_role",
        "ck_request_run_finished_at",
        "ck_request_run_status",
        "uq_conversation_langgraph_thread_id",
        "uq_message_request_role",
        "uq_message_seq",
        "uq_request_run_user_idempotency",
    } <= constraint_names
