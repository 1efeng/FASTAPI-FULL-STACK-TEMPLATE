"""align models with chenguang conventions

Revision ID: 68b9b6583d6f
Revises: fe56fa70289e
Create Date: 2026-08-01 22:11:37.251068

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '68b9b6583d6f'
down_revision = 'fe56fa70289e'
branch_labels = None
depends_on = None


def upgrade():
    # 回填 created_at 中的 NULL 行,否则设 NOT NULL 会失败
    op.execute('UPDATE "user" SET created_at = now() WHERE created_at IS NULL')
    op.execute('UPDATE item SET created_at = now() WHERE created_at IS NULL')

    # ===== item 表 =====
    op.add_column('item', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='更新时间'))
    op.alter_column('item', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               server_default=sa.text('now()'),
               existing_server_default=None,
               nullable=False,
               comment='创建时间')
    op.alter_column('item', 'title',
               existing_type=sa.VARCHAR(length=255),
               comment='标题',
               existing_nullable=False)
    op.alter_column('item', 'description',
               existing_type=sa.VARCHAR(length=255),
               comment='描述',
               existing_nullable=True)
    op.alter_column('item', 'owner_id',
               existing_type=sa.UUID(),
               comment='所属用户ID',
               existing_nullable=False)

    # ===== user 表 =====
    op.add_column('user', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='更新时间'))
    op.alter_column('user', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               server_default=sa.text('now()'),
               existing_server_default=None,
               nullable=False,
               comment='创建时间')
    op.alter_column('user', 'hashed_password',
               existing_type=sa.VARCHAR(),
               type_=sa.String(length=128),
               existing_nullable=False,
               comment='密码哈希')
    op.alter_column('user', 'email',
               existing_type=sa.VARCHAR(length=255),
               comment='邮箱',
               existing_nullable=False)
    op.alter_column('user', 'is_active',
               existing_type=sa.BOOLEAN(),
               comment='是否激活',
               existing_nullable=False)
    op.alter_column('user', 'is_superuser',
               existing_type=sa.BOOLEAN(),
               comment='是否超管',
               existing_nullable=False)
    op.alter_column('user', 'full_name',
               existing_type=sa.VARCHAR(length=255),
               comment='姓名',
               existing_nullable=True)


def downgrade():
    op.alter_column('user', 'full_name',
               existing_type=sa.VARCHAR(length=255),
               comment=None,
               existing_comment='姓名',
               existing_nullable=True)
    op.alter_column('user', 'is_superuser',
               existing_type=sa.BOOLEAN(),
               comment=None,
               existing_comment='是否超管',
               existing_nullable=False)
    op.alter_column('user', 'is_active',
               existing_type=sa.BOOLEAN(),
               comment=None,
               existing_comment='是否激活',
               existing_nullable=False)
    op.alter_column('user', 'email',
               existing_type=sa.VARCHAR(length=255),
               comment=None,
               existing_comment='邮箱',
               existing_nullable=False)
    op.alter_column('user', 'hashed_password',
               existing_type=sa.VARCHAR(),
               type_=sa.VARCHAR(),
               existing_comment='密码哈希',
               existing_nullable=False)
    op.alter_column('user', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               server_default=None,
               existing_server_default=sa.text('now()'),
               nullable=True,
               comment=None,
               existing_comment='创建时间')
    op.drop_column('user', 'updated_at')
    op.alter_column('item', 'owner_id',
               existing_type=sa.UUID(),
               comment=None,
               existing_comment='所属用户ID',
               existing_nullable=False)
    op.alter_column('item', 'description',
               existing_type=sa.VARCHAR(length=255),
               comment=None,
               existing_comment='描述',
               existing_nullable=True)
    op.alter_column('item', 'title',
               existing_type=sa.VARCHAR(length=255),
               comment=None,
               existing_comment='标题',
               existing_nullable=False)
    op.alter_column('item', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               server_default=None,
               existing_server_default=sa.text('now()'),
               nullable=True,
               comment=None,
               existing_comment='创建时间')
    op.drop_column('item', 'updated_at')
