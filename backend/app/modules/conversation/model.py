from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import BaseModel


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Conversation(BaseModel):
    __tablename__ = "conversation"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        comment="所属用户ID",
    )
    title: Mapped[str | None] = mapped_column(
        String(255),
        default=None,
        comment="会话标题",
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        comment="最近一条 durable message 时间",
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        comment="软删除时间",
    )


class Message(BaseModel):
    __tablename__ = "message"

    seq: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        nullable=False,
        comment="稳定消息排序序号",
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversation.id", ondelete="CASCADE"),
        comment="所属会话ID",
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("request_run.id", ondelete="CASCADE"),
        comment="所属请求ID",
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(
            MessageRole,
            name="message_role",
            native_enum=False,
            create_constraint=False,
            values_callable=lambda enum: [member.value for member in enum],
            length=16,
        ),
        comment="业务消息角色",
    )
    content: Mapped[str] = mapped_column(Text, comment="业务消息内容")
    reasoning_summary: Mapped[str | None] = mapped_column(
        Text,
        default=None,
        comment="可公开展示的模型 reasoning summary；仅 assistant 可写",
    )
    source_urls: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        comment="assistant 实际使用的公开来源 URL 列表",
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_message_role",
        ),
        CheckConstraint(
            "role = 'assistant' OR reasoning_summary IS NULL",
            name="ck_message_reasoning_summary_assistant_only",
        ),
        UniqueConstraint("seq", name="uq_message_seq"),
        UniqueConstraint("request_id", "role", name="uq_message_request_role"),
    )


Index(
    "ix_conversation_active_user_last_message",
    Conversation.user_id,
    Conversation.last_message_at.desc(),
    Conversation.id,
    postgresql_where=Conversation.deleted_at.is_(None),
)
Index(
    "ix_message_conversation_seq",
    Message.conversation_id,
    Message.seq,
)
