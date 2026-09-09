from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)
