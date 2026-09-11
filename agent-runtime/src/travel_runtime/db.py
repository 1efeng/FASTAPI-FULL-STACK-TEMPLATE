"""Tool-invocation idempotency ledger owned by the runtime.

Aegra does not provide tool idempotency; the application keeps a minimal
ledger so a tool whose side effect already succeeded is not executed twice
after a crash/restart or checkpoint replay. The table is runtime-owned
(created idempotently) and shares the same PostgreSQL as Aegra/LangGraph.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS tool_invocations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id       VARCHAR(255) NOT NULL,
    tool_name       VARCHAR(255) NOT NULL,
    idempotency_key VARCHAR(255) NOT NULL,
    status          VARCHAR(16)  NOT NULL,
    result          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (thread_id, idempotency_key)
)
"""

# Separate statement: asyncpg prepared statements reject multi-command SQL.
_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS ix_tool_invocations_thread
    ON tool_invocations (thread_id)
"""

_GET_SUCCEEDED = text(
    """
    SELECT result FROM tool_invocations
    WHERE thread_id = :thread_id AND idempotency_key = :key AND status = 'SUCCEEDED'
    LIMIT 1
    """
)

_RECORD = text(
    """
    INSERT INTO tool_invocations (thread_id, tool_name, idempotency_key, status, result)
    VALUES (:thread_id, :tool_name, :key, :status, :result)
    ON CONFLICT (thread_id, idempotency_key)
    DO UPDATE SET status = EXCLUDED.status, result = EXCLUDED.result
    """
)

_engine: AsyncEngine | None = None
_schema_ready = asyncio.Lock()
_schema_done = False


def _env(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _async_dsn() -> str:
    """Build an asyncpg DSN from DATABASE_URL or POSTGRES_* fields."""
    raw = _env("DATABASE_URL")
    if raw:
        prefix = "postgresql+asyncpg://"
        return raw.replace("postgresql://", prefix, 1).replace("postgres://", prefix, 1)
    host = _env("POSTGRES_HOST", "POSTGRES_SERVER") or "localhost"
    port = _env("POSTGRES_PORT") or "5432"
    db = _env("POSTGRES_DB") or ""
    user = _env("POSTGRES_USER") or ""
    password = _env("POSTGRES_PASSWORD") or ""
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(_async_dsn(), pool_pre_ping=True)
    return _engine


async def ensure_schema() -> None:
    """Idempotently create the ledger table (advisory-lock guarded).

    Uses the *transaction-scoped* ``pg_advisory_xact_lock`` so the lock is
    released automatically when the transaction ends (commit or rollback).
    A session-scoped ``pg_advisory_lock`` would survive a failed transaction
    on a pooled connection, wedging every later call behind a leaked lock.
    """
    global _schema_done
    if _schema_done:
        return
    async with _schema_ready:
        if _schema_done:
            return
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('travel_runtime_tool_invocations'))")
            )
            await conn.execute(text(_CREATE_TABLE))
            await conn.execute(text(_CREATE_INDEX))
        _schema_done = True


class ToolInvocationStore:
    """Minimal read/write ledger for replayed tool calls."""

    async def get_succeeded_result(self, *, thread_id: str, idempotency_key: str) -> Any | None:
        await ensure_schema()
        async with get_engine().connect() as conn:
            row = (
                await conn.execute(
                    _GET_SUCCEEDED,
                    {"thread_id": thread_id, "key": idempotency_key},
                )
            ).first()
            if row is None or row[0] is None:
                return None
            if isinstance(row[0], str):
                return json.loads(row[0])
            return row[0]

    async def record(
        self,
        *,
        thread_id: str,
        tool_name: str,
        idempotency_key: str,
        status: str,
        result: Any | None,
    ) -> None:
        await ensure_schema()
        # asyncpg requires JSON values to be pre-serialized strings.
        result_json = json.dumps(result, ensure_ascii=False, default=str) if result is not None else None
        async with get_engine().begin() as conn:
            await conn.execute(
                _RECORD,
                {
                    "thread_id": thread_id,
                    "tool_name": tool_name,
                    "key": idempotency_key,
                    "status": status,
                    "result": result_json,
                },
            )
