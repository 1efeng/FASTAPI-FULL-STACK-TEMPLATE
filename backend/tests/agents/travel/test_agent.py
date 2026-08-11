from typing import Any

import pytest
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.travel import agent as agent_module
from app.agents.travel.middleware import RuntimeClockMiddleware
from app.core.config import settings


def test_build_travel_agent_uses_litellm_model(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    compiled_agent = object()

    def fake_create_deep_agent(**kwargs: Any) -> object:
        captured.update(kwargs)
        return compiled_agent

    monkeypatch.setattr(agent_module, "create_deep_agent", fake_create_deep_agent)
    checkpointer = InMemorySaver()

    result = agent_module.build_travel_agent(
        request_id="request-123",
        trace_id="trace-456",
        metadata={"conversation_id": "conversation-789"},
        checkpointer=checkpointer,
    )

    assert result is compiled_agent
    model = captured["model"]
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == settings.LLM_LOGICAL_MODEL
    assert str(model.openai_api_base).rstrip("/") == (
        f"{settings.LITELLM_BASE_URL.rstrip('/')}/v1"
    )
    assert model.max_retries == 0
    assert model.default_headers == {"X-Client-Request-Id": "request-123"}
    assert model.metadata is not None
    assert model.metadata["trace_id"] == "trace-456"
    assert model.metadata["agent_role"] == "main"
    assert model.metadata["conversation_id"] == "conversation-789"
    assert captured["name"] == "travel-agent"
    assert "Travel Agent" in captured["system_prompt"]
    assert len(captured["middleware"]) == 2
    model_call_limit = captured["middleware"][0]
    assert isinstance(model_call_limit, ModelCallLimitMiddleware)
    assert model_call_limit.run_limit == settings.MODEL_CALL_LIMIT
    assert model_call_limit.thread_limit is None
    assert model_call_limit.exit_behavior == "error"
    assert isinstance(captured["middleware"][1], RuntimeClockMiddleware)
    assert captured["checkpointer"] is checkpointer
