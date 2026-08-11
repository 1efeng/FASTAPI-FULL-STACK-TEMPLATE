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
