import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationTitleMixin(BaseModel):
    title: str | None = Field(default=None, max_length=255)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("title must not be blank")
        return normalized


class ConversationCreate(ConversationTitleMixin):
    pass


class ConversationUpdate(ConversationTitleMixin):
    pass


class MessagePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    reasoning_summary: str | None
    reasoning_duration_ms: int | None
    created_at: datetime


class ConversationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationPublic):
    messages: list[MessagePublic]


class ConversationsPublic(BaseModel):
    data: list[ConversationPublic]
    count: int
