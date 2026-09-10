from uuid import uuid4

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.chat.api import _config
from app.core.config import settings


@pytest.mark.asyncio
async def test_checkpoint_survives_agent_recreation() -> None:
    public_thread_id = f"checkpoint-{uuid4()}"
    config = _config("user-checkpoint", public_thread_id)

    async with AsyncPostgresSaver.from_conn_string(
        str(settings.LANGGRAPH_CHECKPOINT_DATABASE_URI)
    ) as checkpointer:
        await checkpointer.setup()

        first_agent = create_agent(
            model=FakeListChatModel(responses=["first response"]),
            checkpointer=checkpointer,
        )
        await first_agent.ainvoke(
            {"messages": [{"role": "user", "content": "persist me"}]},
            config=config,
        )

        recreated_agent = create_agent(
            model=FakeListChatModel(responses=["unused response"]),
            checkpointer=checkpointer,
        )
        snapshot = await recreated_agent.aget_state(config)

    messages = snapshot.values["messages"]
    assert [message.content for message in messages][-2:] == [
        "persist me",
        "first response",
    ]


@pytest.mark.asyncio
async def test_same_public_thread_id_is_isolated_between_users() -> None:
    public_thread_id = f"shared-{uuid4()}"
    first_config = _config("user-a", public_thread_id)
    second_config = _config("user-b", public_thread_id)

    async with AsyncPostgresSaver.from_conn_string(
        str(settings.LANGGRAPH_CHECKPOINT_DATABASE_URI)
    ) as checkpointer:
        await checkpointer.setup()
        agent = create_agent(
            model=FakeListChatModel(responses=["private response"]),
            checkpointer=checkpointer,
        )

        await agent.ainvoke(
            {"messages": [{"role": "user", "content": "user-a secret"}]},
            config=first_config,
        )

        first_snapshot = await agent.aget_state(first_config)
        second_snapshot = await agent.aget_state(second_config)

    assert first_snapshot.values["messages"]
    assert second_snapshot.values.get("messages", []) == []
