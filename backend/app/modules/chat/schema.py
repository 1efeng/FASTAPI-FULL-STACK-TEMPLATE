import uuid

from pydantic import BaseModel, Field, field_validator


class AgentChatRequest(BaseModel):
    message: str = Field(max_length=20_000)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        message = value.strip()
        if not message:
            raise ValueError("message must not be empty")
        return message


class AgentChatResponse(BaseModel):
    request_id: uuid.UUID
    content: str


class AgentChatError(BaseModel):
    code: str
    message: str
    retryable: bool
    request_id: uuid.UUID
