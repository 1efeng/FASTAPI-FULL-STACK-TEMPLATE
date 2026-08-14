"""Add Product-visible reasoning summary to assistant messages.

Revision ID: 7f2c1d9a4e6b
Revises: c4f4d8a12b7e
Create Date: 2026-08-14
"""

import sqlalchemy as sa
from alembic import op

revision = "7f2c1d9a4e6b"
down_revision = "c4f4d8a12b7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "message",
        sa.Column(
            "reasoning_summary",
            sa.Text(),
            nullable=True,
            comment="可公开展示的模型 reasoning summary；仅 assistant 可写",
        ),
    )
    op.create_check_constraint(
        "ck_message_reasoning_summary_assistant_only",
        "message",
        "role = 'assistant' OR reasoning_summary IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_message_reasoning_summary_assistant_only",
        "message",
        type_="check",
    )
    op.drop_column("message", "reasoning_summary")
