import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.request_run.model import RequestRunStatus


class RequestRunPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    request_id: uuid.UUID = Field(validation_alias="id")
    conversation_id: uuid.UUID
    status: RequestRunStatus
    error_code: str | None
    started_at: datetime
    deadline_at: datetime
    finished_at: datetime | None
    model_requests: int | None
    tool_calls: int | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    research_runs: int | None
    enable_web_search: bool | None
    enable_thinking: bool | None
    context_chars: int | None
    output_chars: int | None
    source_url_count: int | None
    elapsed_ms: int | None
    tool_names: str | None
