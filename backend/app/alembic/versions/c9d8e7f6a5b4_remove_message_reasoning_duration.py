"""Remove measured public reasoning duration from assistant messages.

Revision ID: c9d8e7f6a5b4
Revises: a91e6c3b2d40
Create Date: 2026-03-14
"""

import sqlalchemy as sa
from alembic import op

revision = "c9d8e7f6a5b4"
down_revision = "a91e6c3b2d40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_message_reasoning_duration", "message", type_="check")
    op.drop_column("message", "reasoning_duration_ms")


def downgrade() -> None:
    op.add_column(
        "message",
        sa.Column(
            "reasoning_duration_ms",
            sa.BigInteger(),
            nullable=True,
            comment="公开 reasoning 流片段的累计活跃时长（毫秒）；仅 assistant 可写",
        ),
    )
    op.create_check_constraint(
        "ck_message_reasoning_duration",
        "message",
        "reasoning_duration_ms IS NULL OR "
        "(role = 'assistant' AND reasoning_summary IS NOT NULL "
        "AND reasoning_duration_ms >= 0)",
    )