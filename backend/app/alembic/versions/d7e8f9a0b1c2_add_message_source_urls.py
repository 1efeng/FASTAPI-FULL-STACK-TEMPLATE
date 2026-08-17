"""Persist public source URLs on assistant messages.

Revision ID: d7e8f9a0b1c2
Revises: c9d8e7f6a5b4
Create Date: 2026-08-17
"""

import sqlalchemy as sa
from alembic import op

revision = "d7e8f9a0b1c2"
down_revision = "c9d8e7f6a5b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "message",
        sa.Column(
            "source_urls",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
            comment="assistant 实际使用的公开来源 URL 列表",
        ),
    )


def downgrade() -> None:
    op.drop_column("message", "source_urls")
