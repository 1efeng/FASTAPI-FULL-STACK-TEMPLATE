import re
from typing import Any, cast

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection, sql
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import settings

_SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SETUP_ADVISORY_LOCK_ID = 7_018_327_007


def _normalize_conninfo(database_url: str) -> str:
    for sqlalchemy_scheme in (
        "postgresql+asyncpg://",
        "postgresql+psycopg://",
    ):
        if database_url.startswith(sqlalchemy_scheme):
            return "postgresql://" + database_url.removeprefix(sqlalchemy_scheme)
    return database_url


class LangGraphCheckpointRuntime:
    def __init__(
        self,
        database_url: str,
        schema: str,
        *,
        min_pool_size: int = 1,
        max_pool_size: int = 10,
    ) -> None:
        if not _SCHEMA_PATTERN.fullmatch(schema):
            raise ValueError("Invalid LangGraph database schema")
        self.conninfo = _normalize_conninfo(database_url)
        self.schema = schema
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self._pool: AsyncConnectionPool[AsyncConnection[DictRow]] | None = None
        self._saver: AsyncPostgresSaver | None = None

    @property
    def saver(self) -> AsyncPostgresSaver:
        if self._saver is None:
            raise RuntimeError("LangGraph checkpointer is not initialized")
        return self._saver

    async def _set_search_path(self, connection: AsyncConnection[DictRow]) -> None:
        await connection.execute(
            sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema))
        )

    async def _bootstrap(self) -> None:
        connection = cast(
            AsyncConnection[DictRow],
            await AsyncConnection.connect(
                self.conninfo,
                autocommit=True,
                prepare_threshold=0,
                row_factory=cast(Any, dict_row),
            ),
        )
        try:
            await connection.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                    sql.Identifier(self.schema)
                )
            )
            await self._set_search_path(connection)
            await connection.execute(
                "SELECT pg_advisory_lock(%s)",
                (_SETUP_ADVISORY_LOCK_ID,),
            )
            try:
                await AsyncPostgresSaver(connection).setup()
            finally:
                await connection.execute(
                    "SELECT pg_advisory_unlock(%s)",
                    (_SETUP_ADVISORY_LOCK_ID,),
                )
        finally:
            await connection.close()

    async def start(self) -> None:
        if self._pool is not None:
            return
        await self._bootstrap()
        pool = AsyncConnectionPool(
            self.conninfo,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
            min_size=self.min_pool_size,
            max_size=self.max_pool_size,
            open=False,
            configure=self._set_search_path,
            name="langgraph-checkpoint",
        )
        await pool.open(wait=True)
        self._pool = pool
        self._saver = AsyncPostgresSaver(pool)

    async def close(self) -> None:
        pool = self._pool
        self._pool = None
        self._saver = None
        if pool is not None:
            await pool.close()

    async def delete_thread(self, thread_id: str) -> None:
        await self.saver.adelete_thread(thread_id)


_runtime: LangGraphCheckpointRuntime | None = None


async def init_checkpointer() -> AsyncPostgresSaver:
    global _runtime
    if _runtime is not None:
        return _runtime.saver
    database_url = settings.LANGGRAPH_DATABASE_URL
    if not database_url:
        raise RuntimeError("LANGGRAPH_DATABASE_URL is required")
    runtime = LangGraphCheckpointRuntime(
        database_url=database_url,
        schema=settings.LANGGRAPH_DATABASE_SCHEMA,
    )
    await runtime.start()
    _runtime = runtime
    return runtime.saver


def get_checkpointer() -> AsyncPostgresSaver:
    if _runtime is None:
        raise RuntimeError("LangGraph checkpointer is not initialized")
    return _runtime.saver


async def close_checkpointer() -> None:
    global _runtime
    runtime = _runtime
    _runtime = None
    if runtime is not None:
        await runtime.close()
