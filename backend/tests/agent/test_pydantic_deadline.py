import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from pydantic_ai import Agent, Tool
from pydantic_ai.exceptions import ModelHTTPError
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
        "timeout": settings.LITELLM_CLIENT_TIMEOUT_SECONDS,
        "thinking": True,
        "parallel_tool_calls": True,
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

        def run_stream_native(self, **kwargs):
            captured_run_settings.update(kwargs["model_settings"] or {})

            async def events():
                if False:
                    yield None

            return events()

        def transform_stream(self, stream, *, on_complete=None):
            del on_complete

            async def events():
                async for event in stream:
                    yield event

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
        "timeout": settings.LITELLM_CLIENT_TIMEOUT_SECONDS,
        "thinking": True,
        "parallel_tool_calls": True,
    }


async def _collect_streaming_error(
    error: Exception,
) -> tuple[list[str], list[tuple[str, str | None]]]:
    async def stream_function(messages, info):
        del messages, info
        if False:
            yield None
        raise error

    agent = Agent(
        FunctionModel(stream_function=stream_function),
        model_settings=ModelSettings(
            timeout=settings.LITELLM_CLIENT_TIMEOUT_SECONDS,
        ),
    )
    terminals: list[tuple[str, str | None]] = []

    async def on_terminal(kind: str, reason: str | None) -> str:
        terminals.append((kind, reason))
        return f"safe:{reason or 'INTERNAL_ERROR'}"

    with patch("app.agent.pydantic_executor.get_chat_agent", return_value=agent):
        chunks = [
            chunk
            async for chunk in stream_vercel_events(
                _request(deadline_at=datetime.now(UTC) + timedelta(seconds=30)),
                on_terminal=on_terminal,
            )
        ]
    return chunks, terminals


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (408, "MODEL_TIMEOUT"),
        (429, "MODEL_RATE_LIMITED"),
        (503, "MODEL_UNAVAILABLE"),
    ],
)
async def test_streaming_typed_model_errors_are_safely_classified(
    status_code: int,
    expected_code: str,
) -> None:
    raw_provider_detail = "private-provider-model sk-secret-upstream-detail"
    chunks, terminals = await _collect_streaming_error(
        ModelHTTPError(
            status_code=status_code,
            model_name="private-provider-model",
            body={"error": raw_provider_detail},
        )
    )

    assert terminals == [("error", expected_code)]
    assert f"safe:{expected_code}" in chunks
    assert raw_provider_detail not in "".join(chunks)


async def test_streaming_unknown_error_is_internal_and_sanitized() -> None:
    raw_framework_detail = "private-framework-secret"
    chunks, terminals = await _collect_streaming_error(
        RuntimeError(raw_framework_detail)
    )

    assert terminals == [("error", None)]
    assert "safe:INTERNAL_ERROR" in chunks
    assert raw_framework_detail not in "".join(chunks)


async def test_streaming_user_cancel_bypasses_model_error_mapping() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    terminals: list[tuple[str, str | None]] = []

    async def stream_function(messages, info):
        del messages, info
        started.set()
        await release.wait()
        if False:
            yield None

    agent = Agent(FunctionModel(stream_function=stream_function))

    async def on_terminal(kind: str, reason: str | None) -> str:
        terminals.append((kind, reason))
        return "unexpected terminal"

    async def collect() -> list[str]:
        with patch("app.agent.pydantic_executor.get_chat_agent", return_value=agent):
            return [
                chunk
                async for chunk in stream_vercel_events(
                    _request(deadline_at=datetime.now(UTC) + timedelta(seconds=30)),
                    on_terminal=on_terminal,
                )
            ]

    task = asyncio.create_task(collect())
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert terminals == []
