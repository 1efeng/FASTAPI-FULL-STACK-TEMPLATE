import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from pydantic_ai import Agent, Tool
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.settings import ModelSettings

from app.agent.executor import AgentExecutionRequest
from app.agent.pydantic_executor import (
    PydanticAIExecutor,
    get_chat_agent,
    stream_vercel_events,
)
from app.core.config import settings


def _request(*, deadline_at: datetime) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        request_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message="hello",
        history=(),
        deadline_at=deadline_at,
    )


async def test_expired_product_deadline_is_not_enforced_by_executor() -> None:
    called = False

    def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        nonlocal called
        called = True
        return ModelResponse(parts=[TextPart("late but valid at executor boundary")])

    executor = PydanticAIExecutor(Agent(FunctionModel(model_function)))

    result = await executor.execute(
        _request(deadline_at=datetime.now(UTC) - timedelta(seconds=1))
    )

    assert result.content == "late but valid at executor boundary"
    assert called is True


def test_main_agent_uses_rpc_timeout_and_disables_sdk_retries() -> None:
    agent = get_chat_agent()
    model = agent.model
    provider = model.provider

    assert agent.model_settings == {
        "timeout": settings.LITELLM_CLIENT_TIMEOUT_SECONDS
    }
    assert provider.client.max_retries == 0


async def test_non_stream_model_requests_receive_rpc_timeout() -> None:
    observed_timeouts: list[float] = []
    model_calls = 0

    def deadline_probe() -> str:
        return "tool complete"

    def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages
        nonlocal model_calls
        model_calls += 1
        assert info.model_settings is not None
        observed_timeouts.append(float(info.model_settings["timeout"]))
        if model_calls == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="deadline_probe", args={})]
            )
        return ModelResponse(parts=[TextPart("done")])

    agent: Agent[object, str] = Agent(
        FunctionModel(model_function),
        model_settings=ModelSettings(
            timeout=settings.LITELLM_CLIENT_TIMEOUT_SECONDS,
        ),
        tools=[Tool[object](deadline_probe, takes_ctx=False)],
    )
    executor = PydanticAIExecutor(agent)

    result = await executor.execute(
        _request(deadline_at=datetime.now(UTC) - timedelta(seconds=1))
    )

    assert result.content == "done"
    assert observed_timeouts == [
        settings.LITELLM_CLIENT_TIMEOUT_SECONDS,
        settings.LITELLM_CLIENT_TIMEOUT_SECONDS,
    ]


async def test_stream_model_requests_receive_same_rpc_timeout() -> None:
    captured_agent_settings: dict[str, object] = {}
    captured_run_settings: dict[str, object] = {}

    class FakeAdapter:
        def __init__(self, *, agent, **kwargs) -> None:
            del kwargs
            captured_agent_settings.update(agent.model_settings or {})

        def run_stream(self, **kwargs):
            captured_run_settings.update(kwargs["model_settings"] or {})

            async def events():
                if False:
                    yield None

            return events()

        async def encode_stream(self, stream):
            del stream
            yield "data: [DONE]\n\n"

    request = _request(deadline_at=datetime.now(UTC) - timedelta(seconds=1))
    with patch(
        "app.agent.pydantic_executor.VercelAIAdapter",
        FakeAdapter,
    ):
        chunks = [chunk async for chunk in stream_vercel_events(request)]

    assert chunks == ["data: [DONE]\n\n"]
    assert captured_agent_settings == {
        "timeout": settings.LITELLM_CLIENT_TIMEOUT_SECONDS
    }
    assert captured_run_settings == {
        "timeout": settings.LITELLM_CLIENT_TIMEOUT_SECONDS
    }
