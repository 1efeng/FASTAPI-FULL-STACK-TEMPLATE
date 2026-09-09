"""add item copy sample

Revision ID: e7a1c9d4b205
Revises: c2f4d8e7a123
Create Date: 2026-09-09
"""

import sqlalchemy as sa
from alembic import op

revision = "e7a1c9d4b205"
down_revision = "c2f4d8e7a123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "item",
        sa.Column("title", sa.String(length=255), nullable=False, comment="标题"),
        sa.Column(
            "description",
            sa.String(length=255),
            nullable=True,
            comment="描述",
        ),
        sa.Column("owner_id", sa.UUID(), nullable=False, comment="所属用户ID"),
        sa.Column("id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_item_owner_id", "item", ["owner_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_item_owner_id", table_name="item")
    op.drop_table("item")
