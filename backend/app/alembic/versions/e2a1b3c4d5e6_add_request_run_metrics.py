"""Add runtime metrics columns to request_run.

Revision ID: e2a1b3c4d5e6
Revises: d7e8f9a0b1c2
Create Date: 2026-08-19
"""

import sqlalchemy as sa
from alembic import op

revision = "e2a1b3c4d5e6"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "request_run",
        sa.Column(
            "model_requests",
            sa.BigInteger(),
            nullable=True,
            comment="模型请求总次数（Main + research 子 agent）",
        ),
    )
    op.add_column(
        "request_run",
        sa.Column(
            "tool_calls",
            sa.BigInteger(),
            nullable=True,
            comment="工具调用总次数（Main + research 子 agent）",
        ),
    )
    op.add_column(
        "request_run",
        sa.Column(
            "input_tokens",
            sa.BigInteger(),
            nullable=True,
            comment="输入 token 累计；provider 未报告时为 NULL",
        ),
    )
    op.add_column(
        "request_run",
        sa.Column(
            "output_tokens",
            sa.BigInteger(),
            nullable=True,
            comment="输出 token 累计；provider 未报告时为 NULL",
        ),
    )
    op.add_column(
        "request_run",
        sa.Column(
            "total_tokens",
            sa.BigInteger(),
            nullable=True,
            comment="输入 + 输出 token 累计；provider 未报告时为 NULL",
        ),
    )
    op.add_column(
        "request_run",
        sa.Column(
            "cache_read_tokens",
            sa.BigInteger(),
            nullable=True,
            comment="缓存读 token 累计；provider 未报告时为 NULL",
        ),
    )
    op.add_column(
        "request_run",
        sa.Column(
            "cache_write_tokens",
            sa.BigInteger(),
            nullable=True,
            comment="缓存写 token 累计；provider 未报告时为 NULL",
        ),
    )
    op.add_column(
        "request_run",
        sa.Column(
            "research_runs",
            sa.BigInteger(),
            nullable=True,
            comment="本次请求触发的 research 子 agent 调用次数",
        ),
    )
    op.add_column(
        "request_run",
        sa.Column(
            "enable_web_search",
            sa.Boolean(),
            nullable=True,
            comment="请求是否开启联网搜索",
        ),
    )
    op.add_column(
        "request_run",
        sa.Column(
            "enable_thinking",
            sa.Boolean(),
            nullable=True,
            comment="请求是否开启模型 thinking",
        ),
    )


def downgrade() -> None:
    op.drop_column("request_run", "enable_thinking")
    op.drop_column("request_run", "enable_web_search")
    op.drop_column("request_run", "research_runs")
    op.drop_column("request_run", "cache_write_tokens")
    op.drop_column("request_run", "cache_read_tokens")
    op.drop_column("request_run", "total_tokens")
    op.drop_column("request_run", "output_tokens")
    op.drop_column("request_run", "input_tokens")
    op.drop_column("request_run", "tool_calls")
    op.drop_column("request_run", "model_requests")