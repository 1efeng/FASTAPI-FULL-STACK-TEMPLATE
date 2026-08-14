"""Add measured public reasoning duration to assistant messages.

Revision ID: a91e6c3b2d40
Revises: 7f2c1d9a4e6b
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "a91e6c3b2d40"
down_revision = "7f2c1d9a4e6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_constraint(
        "ck_message_reasoning_duration", "message", type_="check"
    )
    op.drop_column("message", "reasoning_duration_ms")
