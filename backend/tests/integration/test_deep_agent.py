import os
import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.travel import build_travel_agent


@pytest.mark.asyncio
async def test_deep_agent_live_completion_through_litellm() -> None:
    if os.getenv("RUN_DEEPAGENTS_INTEGRATION") != "1":
        pytest.skip(
            "set RUN_DEEPAGENTS_INTEGRATION=1 to test Deep Agents through LiteLLM"
        )

    agent = build_travel_agent(
        request_id="deep-agent-integration-request",
        trace_id="deep-agent-integration-trace",
        metadata={"test": True},
        checkpointer=InMemorySaver(),
    )
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "Reply with exactly OK."}]},
        config={
            "configurable": {"thread_id": str(uuid.uuid4())},
        },
    )

    assert result["messages"][-1].content.strip()
