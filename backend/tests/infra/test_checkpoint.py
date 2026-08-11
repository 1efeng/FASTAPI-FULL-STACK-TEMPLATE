import uuid
from dataclasses import dataclass, field
from operator import add
from typing import Annotated, Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.infra.checkpoint import LangGraphCheckpointRuntime


@dataclass
class CheckpointState:
    values: Annotated[list[str], add] = field(default_factory=list)


async def _checkpoint_node(state: CheckpointState) -> dict[str, list[str]]:
    del state
    return {}


def _build_graph(checkpointer: AsyncPostgresSaver) -> Any:
    builder = StateGraph(CheckpointState)
    builder.add_node("checkpoint", _checkpoint_node)
    builder.add_edge(START, "checkpoint")
    builder.add_edge("checkpoint", END)
    return builder.compile(checkpointer=checkpointer)


def _thread_config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


async def test_postgres_checkpointer_bootstrap_restart_multi_instance_and_delete(
    db: AsyncSession,
) -> None:
    database_url = str(settings.SQLALCHEMY_DATABASE_URI)
    schema = settings.LANGGRAPH_DATABASE_SCHEMA
    thread_a = f"m5-a-{uuid.uuid4()}"
    thread_b = f"m5-b-{uuid.uuid4()}"
    config_a = _thread_config(thread_a)
    config_b = _thread_config(thread_b)

    runtime_one = LangGraphCheckpointRuntime(database_url, schema)
    await runtime_one.start()
    try:
        tables = set(
            (
                await db.execute(
                    text(
                        """
                        SELECT table_name
                        FROM information_schema.tables
                        WHERE table_schema = :schema
                        """
                    ),
                    {"schema": schema},
                )
            )
            .scalars()
            .all()
        )
        assert {
            "checkpoint_migrations",
            "checkpoints",
            "checkpoint_blobs",
            "checkpoint_writes",
        } <= tables

        graph_one = _build_graph(runtime_one.saver)
        await graph_one.ainvoke({"values": ["first"]}, config=config_a)
        await graph_one.ainvoke({"values": ["private-b"]}, config=config_b)
    finally:
        await runtime_one.close()

    runtime_two = LangGraphCheckpointRuntime(database_url, schema)
    await runtime_two.start()
    runtime_three = LangGraphCheckpointRuntime(database_url, schema)
    await runtime_three.start()
    try:
        graph_two = _build_graph(runtime_two.saver)
        resumed = await graph_two.aget_state(config_a)
        assert resumed.values["values"] == ["first"]

        graph_three = _build_graph(runtime_three.saver)
        await graph_three.ainvoke({"values": ["second"]}, config=config_a)

        shared_state = await graph_two.aget_state(config_a)
        isolated_state = await graph_two.aget_state(config_b)
        assert shared_state.values["values"] == ["first", "second"]
        assert isolated_state.values["values"] == ["private-b"]

        await runtime_three.delete_thread(thread_a)
        deleted_state = await graph_two.aget_state(config_a)
        retained_state = await graph_two.aget_state(config_b)
        assert deleted_state.values == {}
        assert retained_state.values["values"] == ["private-b"]
        await runtime_two.delete_thread(thread_b)
    finally:
        await runtime_three.close()
        await runtime_two.close()


async def test_langgraph_schema_name_is_validated() -> None:
    database_url = str(settings.SQLALCHEMY_DATABASE_URI)

    try:
        LangGraphCheckpointRuntime(database_url, "invalid-schema;drop")
    except ValueError as exc:
        assert str(exc) == "Invalid LangGraph database schema"
    else:
        raise AssertionError("invalid schema must be rejected")
