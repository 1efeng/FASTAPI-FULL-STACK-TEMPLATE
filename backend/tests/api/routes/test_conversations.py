import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.conversation.model import Conversation, Message, MessageRole
from app.modules.request_run.model import RequestRun, RequestRunStatus
from app.modules.user.service import UserService


async def _current_superuser_id(db: AsyncSession) -> uuid.UUID:
    user = await UserService(db).get_by_email(settings.FIRST_SUPERUSER)
    assert user is not None
    return user.id


async def _create_conversation(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    title: str | None,
    last_message_at: datetime | None = None,
    deleted_at: datetime | None = None,
) -> Conversation:
    conversation = Conversation(
        user_id=user_id,
        title=title,
        last_message_at=last_message_at,
        deleted_at=deleted_at,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


async def test_conversation_routes_require_authentication(client: AsyncClient) -> None:
    response = await client.get(f"{settings.API_V1_STR}/conversations/")
    assert response.status_code == 401


async def test_create_conversation_hides_internal_ownership_fields(
    client: AsyncClient, normal_user_token_headers: dict[str, str]
) -> None:
    response = await client.post(
        f"{settings.API_V1_STR}/conversations/",
        headers=normal_user_token_headers,
        json={"title": "  Tokyo plan  "},
    )

    assert response.status_code == 200
    content = response.json()
    assert content["title"] == "Tokyo plan"
    assert content["last_message_at"] is None
    assert "id" in content
    assert set(content) == {"id", "title", "last_message_at", "created_at", "updated_at"}


async def test_list_conversations_is_owned_active_and_stably_ordered(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    user_id = await _current_superuser_id(db)
    now = datetime.now(UTC)
    older = await _create_conversation(
        db, user_id, title="Older", last_message_at=now - timedelta(hours=1)
    )
    newer = await _create_conversation(db, user_id, title="Newer", last_message_at=now)
    no_messages = await _create_conversation(
        db, user_id, title="No messages", last_message_at=None
    )
    await _create_conversation(
        db,
        user_id,
        title="Deleted",
        last_message_at=now + timedelta(hours=1),
        deleted_at=now,
    )
    other_response = await client.post(
        f"{settings.API_V1_STR}/conversations/",
        headers=normal_user_token_headers,
        json={"title": "Other user's conversation"},
    )
    assert other_response.status_code == 200

    response = await client.get(
        f"{settings.API_V1_STR}/conversations/",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    assert content["count"] == 3
    assert [item["id"] for item in content["data"]] == [
        str(newer.id),
        str(older.id),
        str(no_messages.id),
    ]


async def test_read_conversation_returns_only_ordered_business_messages(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    user_id = await _current_superuser_id(db)
    conversation = await _create_conversation(db, user_id, title="With messages")
    now = datetime.now(UTC)
    request_run = RequestRun(
        user_id=user_id,
        conversation_id=conversation.id,
        idempotency_key=f"test-{uuid.uuid4()}",
        status=RequestRunStatus.COMPLETED,
        started_at=now,
        deadline_at=now + timedelta(seconds=30),
        finished_at=now,
    )
    db.add(request_run)
    await db.flush()
    db.add_all(
        [
            Message(
                conversation_id=conversation.id,
                request_id=request_run.id,
                role=MessageRole.USER,
                content="Plan Tokyo",
                reasoning_summary=None,
            ),
            Message(
                conversation_id=conversation.id,
                request_id=request_run.id,
                role=MessageRole.ASSISTANT,
                content="Here is a draft.",
                reasoning_summary="先比较交通时间，再安排每日区域。",
            ),
        ]
    )
    await db.commit()

    response = await client.get(
        f"{settings.API_V1_STR}/conversations/{conversation.id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    assert content["id"] == str(conversation.id)
    assert [message["role"] for message in content["messages"]] == [
        "user",
        "assistant",
    ]
    assert [message["content"] for message in content["messages"]] == [
        "Plan Tokyo",
        "Here is a draft.",
    ]
    assert [message["reasoning_summary"] for message in content["messages"]] == [
        None,
        "先比较交通时间，再安排每日区域。",
    ]
    assert "seq" not in content["messages"][0]
    assert "request_id" not in content["messages"][0]


async def test_update_conversation_supports_title_change_and_clear(
    client: AsyncClient, normal_user_token_headers: dict[str, str]
) -> None:
    created = await client.post(
        f"{settings.API_V1_STR}/conversations/",
        headers=normal_user_token_headers,
        json={"title": "Draft"},
    )
    conversation_id = created.json()["id"]

    updated = await client.patch(
        f"{settings.API_V1_STR}/conversations/{conversation_id}",
        headers=normal_user_token_headers,
        json={"title": "  Final title  "},
    )
    cleared = await client.patch(
        f"{settings.API_V1_STR}/conversations/{conversation_id}",
        headers=normal_user_token_headers,
        json={"title": None},
    )

    assert updated.status_code == 200
    assert updated.json()["title"] == "Final title"
    assert cleared.status_code == 200
    assert cleared.json()["title"] is None


async def test_other_user_cannot_read_update_or_delete_conversation(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    normal_user_token_headers: dict[str, str],
) -> None:
    created = await client.post(
        f"{settings.API_V1_STR}/conversations/",
        headers=normal_user_token_headers,
        json={"title": "Private"},
    )
    conversation_id = created.json()["id"]

    responses = [
        await client.get(
            f"{settings.API_V1_STR}/conversations/{conversation_id}",
            headers=superuser_token_headers,
        ),
        await client.patch(
            f"{settings.API_V1_STR}/conversations/{conversation_id}",
            headers=superuser_token_headers,
            json={"title": "Stolen"},
        ),
        await client.delete(
            f"{settings.API_V1_STR}/conversations/{conversation_id}",
            headers=superuser_token_headers,
        ),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404]
    assert all(
        response.json()["detail"] == "Conversation not found" for response in responses
    )
    owner_response = await client.get(
        f"{settings.API_V1_STR}/conversations/{conversation_id}",
        headers=normal_user_token_headers,
    )
    assert owner_response.status_code == 200
    assert owner_response.json()["title"] == "Private"


async def test_delete_conversation_is_soft_and_hides_it_from_product_queries(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    db: AsyncSession,
) -> None:
    created = await client.post(
        f"{settings.API_V1_STR}/conversations/",
        headers=superuser_token_headers,
        json={"title": "Delete me"},
    )
    conversation_id = uuid.UUID(created.json()["id"])

    deleted = await client.delete(
        f"{settings.API_V1_STR}/conversations/{conversation_id}",
        headers=superuser_token_headers,
    )
    detail = await client.get(
        f"{settings.API_V1_STR}/conversations/{conversation_id}",
        headers=superuser_token_headers,
    )
    listing = await client.get(
        f"{settings.API_V1_STR}/conversations/",
        headers=superuser_token_headers,
    )
    persisted = (
        await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    ).scalar_one()

    assert deleted.status_code == 200
    assert deleted.json() == {"message": "Conversation deleted successfully"}
    assert detail.status_code == 404
    assert listing.status_code == 200
    assert listing.json()["count"] == 0
    assert persisted.deleted_at is not None
