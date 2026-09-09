from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
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
    # ---- 运行指标（AgentUsage 总账，一次请求一行） ----
    model_requests: Mapped[int | None] = mapped_column(
        BigInteger,
        default=None,
        comment="模型请求总次数（Main + research 子 agent）",
    )
    tool_calls: Mapped[int | None] = mapped_column(
        BigInteger,
        default=None,
        comment="工具调用总次数（Main + research 子 agent）",
    )
    input_tokens: Mapped[int | None] = mapped_column(
        BigInteger,
        default=None,
        comment="输入 token 累计；provider 未报告时为 NULL",
    )
    output_tokens: Mapped[int | None] = mapped_column(
        BigInteger,
        default=None,
        comment="输出 token 累计；provider 未报告时为 NULL",
    )
    total_tokens: Mapped[int | None] = mapped_column(
        BigInteger,
        default=None,
        comment="输入 + 输出 token 累计；provider 未报告时为 NULL",
    )
    cache_read_tokens: Mapped[int | None] = mapped_column(
        BigInteger,
        default=None,
        comment="缓存读 token 累计；provider 未报告时为 NULL",
    )
    cache_write_tokens: Mapped[int | None] = mapped_column(
        BigInteger,
        default=None,
        comment="缓存写 token 累计；provider 未报告时为 NULL",
    )
    research_runs: Mapped[int | None] = mapped_column(
        BigInteger,
        default=None,
        comment="本次请求触发的 research 子 agent 调用次数",
    )
    enable_web_search: Mapped[bool | None] = mapped_column(
        Boolean,
        default=None,
        comment="请求是否开启联网搜索",
    )
    enable_thinking: Mapped[bool | None] = mapped_column(
        Boolean,
        default=None,
        comment="请求是否开启模型 thinking",
    )
    context_chars: Mapped[int | None] = mapped_column(
        BigInteger,
        default=None,
        comment="本次 Agent 运行观测到的上下文字符数（不含原文）",
    )
    output_chars: Mapped[int | None] = mapped_column(
        BigInteger,
        default=None,
        comment="最终模型输出字符数",
    )
    source_url_count: Mapped[int | None] = mapped_column(
        BigInteger,
        default=None,
        comment="本次运行产生的来源 URL 数量",
    )
    elapsed_ms: Mapped[int | None] = mapped_column(
        BigInteger,
        default=None,
        comment="Agent 运行耗时（毫秒）",
    )
    tool_names: Mapped[str | None] = mapped_column(
        String(1024),
        default=None,
        comment="本次运行调用过的工具名，逗号分隔",
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
