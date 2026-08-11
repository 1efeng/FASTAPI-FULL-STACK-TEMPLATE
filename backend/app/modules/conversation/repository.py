import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_repository import BaseRepository
from app.modules.conversation.model import Conversation, Message


class ConversationRepository(BaseRepository[Conversation]):
    def __init__(self, db: AsyncSession):
        super().__init__(Conversation, db)

    async def get_owned_active(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> Conversation | None:
        statement = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        return (await self.db.execute(statement)).scalar_one_or_none()

    async def list_owned_active(
        self, user_id: uuid.UUID, skip: int, limit: int
    ) -> tuple[list[Conversation], int]:
        filters = (
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        count_statement = select(func.count()).select_from(Conversation).where(*filters)
        statement = (
            select(Conversation)
            .where(*filters)
            .order_by(
                Conversation.last_message_at.desc().nulls_last(),
                Conversation.created_at.desc(),
                Conversation.id,
            )
            .offset(skip)
            .limit(limit)
        )
        count = (await self.db.execute(count_statement)).scalar_one()
        conversations = (await self.db.execute(statement)).scalars().all()
        return list(conversations), count

    async def create_message(self, message: Message) -> Message:
        self.db.add(message)
        await self.db.flush()
        await self.db.refresh(message)
        return message

    async def list_messages(self, conversation_id: uuid.UUID) -> list[Message]:
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.seq)
        )
        messages = (await self.db.execute(statement)).scalars().all()
        return list(messages)
