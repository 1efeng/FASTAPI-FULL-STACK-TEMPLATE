"""Make user email uniqueness case-insensitive.

Revision ID: b7198f0d2c4a
Revises: 68b9b6583d6f
Create Date: 2026-08-10
"""

import sqlalchemy as sa
from alembic import op

revision = "b7198f0d2c4a"
down_revision = "68b9b6583d6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicates = connection.execute(
        sa.text(
            """
            SELECT lower(email)
            FROM "user"
            GROUP BY lower(email)
            HAVING count(*) > 1
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    if duplicates is not None:
        raise RuntimeError(
            "Cannot make user emails case-insensitive: duplicate emails exist "
            f"for normalized value {duplicates!r}"
        )

    op.execute(sa.text('UPDATE "user" SET email = lower(email)'))
    op.drop_index("ix_user_email", table_name="user")
    op.create_index(
        "ix_user_email",
        "user",
        [sa.text("lower(email)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_user_email", table_name="user")
    op.create_index("ix_user_email", "user", ["email"], unique=True)
