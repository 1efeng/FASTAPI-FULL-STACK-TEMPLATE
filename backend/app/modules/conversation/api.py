import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.core.base_schema import Message
from app.core.deps import CurrentUser, SessionDep
from app.modules.conversation.schema import (
    ConversationCreate,
    ConversationDetail,
    ConversationPublic,
    ConversationsPublic,
    ConversationUpdate,
    MessagePublic,
)
from app.modules.conversation.service import ConversationService

router = APIRouter(prefix="/conversations", tags=["conversations"])
SkipParam = Annotated[int, Query(ge=0)]
LimitParam = Annotated[int, Query(ge=1, le=100)]


def get_conversation_service(db: SessionDep) -> ConversationService:
    return ConversationService(db)


@router.get("/", response_model=ConversationsPublic)
async def read_conversations(
    current_user: CurrentUser,
    skip: SkipParam = 0,
    limit: LimitParam = 100,
    svc: ConversationService = Depends(get_conversation_service),
) -> Any:
    conversations, count = await svc.list_conversations(current_user.id, skip, limit)
    return ConversationsPublic(
        data=[ConversationPublic.model_validate(item) for item in conversations],
        count=count,
    )


@router.post("/", response_model=ConversationPublic)
async def create_conversation(
    current_user: CurrentUser,
    conversation_in: ConversationCreate,
    svc: ConversationService = Depends(get_conversation_service),
) -> Any:
    return await svc.create_conversation(conversation_in, current_user.id)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def read_conversation(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    svc: ConversationService = Depends(get_conversation_service),
) -> Any:
    conversation, messages = await svc.get_conversation_detail(
        conversation_id, current_user.id
    )
    public = ConversationPublic.model_validate(conversation)
    return ConversationDetail(
        **public.model_dump(),
        messages=[MessagePublic.model_validate(message) for message in messages],
    )


@router.patch("/{conversation_id}", response_model=ConversationPublic)
async def update_conversation(
    conversation_id: uuid.UUID,
    conversation_in: ConversationUpdate,
    current_user: CurrentUser,
    svc: ConversationService = Depends(get_conversation_service),
) -> Any:
    return await svc.update_conversation(
        conversation_id, conversation_in, current_user.id
    )


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    svc: ConversationService = Depends(get_conversation_service),
) -> Message:
    await svc.delete_conversation(conversation_id, current_user.id)
    return Message(message="Conversation deleted successfully")
