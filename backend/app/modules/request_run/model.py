from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class RequestRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RequestRun(BaseModel):
    __tablename__ = "request_run"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        comment="所属用户ID",
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"),
        comment="所属会话ID",
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        comment="用户作用域幂等键",
    )
    status: Mapped[RequestRunStatus] = mapped_column(
        Enum(
            RequestRunStatus,
            name="request_run_status",
            native_enum=False,
            create_constraint=False,
            values_callable=lambda enum: [member.value for member in enum],
            length=16,
        ),
        comment="请求生命周期状态",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        comment="请求开始时间",
    )
    deadline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        comment="请求绝对截止时间",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        comment="请求终态时间",
    )
    error_code: Mapped[str | None] = mapped_column(
        String(64),
        default=None,
        comment="产品错误码",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'cancelled')",
            name="ck_request_run_status",
        ),
        CheckConstraint(
            "(status = 'running' AND finished_at IS NULL) OR "
            "(status IN ('completed', 'failed', 'cancelled') "
            "AND finished_at IS NOT NULL)",
            name="ck_request_run_finished_at",
        ),
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_request_run_user_idempotency",
        ),
    )


Index(
    "ix_request_run_conversation_created_at",
    RequestRun.conversation_id,
    RequestRun.created_at.desc(),
)
Index(
    "ix_request_run_running_deadline",
    RequestRun.deadline_at,
    postgresql_where=RequestRun.status == RequestRunStatus.RUNNING,
)
Index(
    "uq_request_run_one_running_per_conversation",
    RequestRun.conversation_id,
    unique=True,
    postgresql_where=RequestRun.status == RequestRunStatus.RUNNING,
)
