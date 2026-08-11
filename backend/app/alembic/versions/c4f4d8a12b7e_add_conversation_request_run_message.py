"""Add conversation, request_run, and message business tables.

Revision ID: c4f4d8a12b7e
Revises: b7198f0d2c4a
Create Date: 2026-08-11
"""

import sqlalchemy as sa
from alembic import op

revision = "c4f4d8a12b7e"
down_revision = "b7198f0d2c4a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation",
        sa.Column("user_id", sa.Uuid(), nullable=False, comment="所属用户ID"),
        sa.Column("title", sa.String(length=255), nullable=True, comment="会话标题"),
        sa.Column(
            "langgraph_thread_id",
            sa.Uuid(),
            nullable=False,
            comment="LangGraph runtime thread opaque mapping",
        ),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近一条 durable message 时间",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="软删除时间",
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="更新时间",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name="fk_conversation_user_id_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversation"),
        sa.UniqueConstraint(
            "langgraph_thread_id",
            name="uq_conversation_langgraph_thread_id",
        ),
    )
    op.create_index(
        "ix_conversation_active_user_last_message",
        "conversation",
        ["user_id", sa.text("last_message_at DESC"), "id"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "request_run",
        sa.Column("user_id", sa.Uuid(), nullable=False, comment="所属用户ID"),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            nullable=False,
            comment="所属会话ID",
        ),
        sa.Column(
            "idempotency_key",
            sa.String(length=255),
            nullable=False,
            comment="用户作用域幂等键",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            comment="请求生命周期状态",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="请求开始时间",
        ),
        sa.Column(
            "deadline_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="请求绝对截止时间",
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="请求终态时间",
        ),
        sa.Column(
            "error_code",
            sa.String(length=64),
            nullable=True,
            comment="产品错误码",
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="更新时间",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND finished_at IS NULL) OR "
            "(status IN ('completed', 'failed', 'cancelled') "
            "AND finished_at IS NOT NULL)",
            name="ck_request_run_finished_at",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'cancelled')",
            name="ck_request_run_status",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name="fk_request_run_conversation_id_conversation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name="fk_request_run_user_id_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_request_run"),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_request_run_user_idempotency",
        ),
    )
    op.create_index(
        "ix_request_run_conversation_created_at",
        "request_run",
        ["conversation_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_request_run_running_deadline",
        "request_run",
        ["deadline_at"],
        unique=False,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "uq_request_run_one_running_per_conversation",
        "request_run",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )

    op.create_table(
        "message",
        sa.Column(
            "seq",
            sa.BigInteger(),
            sa.Identity(),
            nullable=False,
            comment="稳定消息排序序号",
        ),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            nullable=False,
            comment="所属会话ID",
        ),
        sa.Column("request_id", sa.Uuid(), nullable=False, comment="所属请求ID"),
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=False,
            comment="业务消息角色",
        ),
        sa.Column("content", sa.Text(), nullable=False, comment="业务消息内容"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="更新时间",
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_message_role",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name="fk_message_conversation_id_conversation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["request_run.id"],
            name="fk_message_request_id_request_run",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_message"),
        sa.UniqueConstraint(
            "request_id",
            "role",
            name="uq_message_request_role",
        ),
        sa.UniqueConstraint("seq", name="uq_message_seq"),
    )
    op.create_index(
        "ix_message_conversation_seq",
        "message",
        ["conversation_id", "seq"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_message_conversation_seq", table_name="message")
    op.drop_table("message")
    op.drop_index(
        "uq_request_run_one_running_per_conversation",
        table_name="request_run",
        postgresql_where=sa.text("status = 'running'"),
    )
    op.drop_index(
        "ix_request_run_running_deadline",
        table_name="request_run",
        postgresql_where=sa.text("status = 'running'"),
    )
    op.drop_index(
        "ix_request_run_conversation_created_at",
        table_name="request_run",
    )
    op.drop_table("request_run")
    op.drop_index(
        "ix_conversation_active_user_last_message",
        table_name="conversation",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_table("conversation")
