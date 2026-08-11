import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.model import Conversation, Message
from app.modules.conversation.repository import ConversationRepository
from app.modules.conversation.schema import ConversationCreate, ConversationUpdate


class ConversationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ConversationRepository(db)

    async def list_conversations(
        self, user_id: uuid.UUID, skip: int, limit: int
    ) -> tuple[list[Conversation], int]:
        return await self.repo.list_owned_active(user_id, skip, limit)

    async def get_conversation(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> Conversation:
        conversation = await self.repo.get_owned_active(conversation_id, user_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return conversation

    async def get_conversation_detail(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[Conversation, list[Message]]:
        conversation = await self.get_conversation(conversation_id, user_id)
        messages = await self.repo.list_messages(conversation.id)
        return conversation, messages

    async def create_conversation(
        self, conversation_in: ConversationCreate, user_id: uuid.UUID
    ) -> Conversation:
        conversation = Conversation(user_id=user_id, title=conversation_in.title)
        conversation = await self.repo.create(conversation)
        await self.db.commit()
        return conversation

    async def update_conversation(
        self,
        conversation_id: uuid.UUID,
        conversation_in: ConversationUpdate,
        user_id: uuid.UUID,
    ) -> Conversation:
        conversation = await self.get_conversation(conversation_id, user_id)
        if "title" in conversation_in.model_fields_set:
            conversation.title = conversation_in.title
        conversation = await self.repo.update(conversation)
        await self.db.commit()
        return conversation

    async def delete_conversation(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        conversation = await self.get_conversation(conversation_id, user_id)
        conversation.deleted_at = datetime.now(UTC)
        await self.repo.update(conversation)
        await self.db.commit()
