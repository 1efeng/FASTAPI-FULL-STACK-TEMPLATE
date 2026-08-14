import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from openai import APITimeoutError
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agent.executor import AgentExecutionError, AgentExecutionRequest
from app.agent.pydantic_executor import PydanticAIExecutor

_RAW_PROVIDER_DETAILS = "private-provider-model sk-secret-upstream-detail"


def _request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        request_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message="hello",
        history=(),
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
    )


async def _execute_raising(exc: Exception) -> AgentExecutionError:
    def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        raise exc

    executor = PydanticAIExecutor(Agent(FunctionModel(model_function)))
    with pytest.raises(AgentExecutionError) as captured:
        await executor.execute(_request())
    return captured.value


def _assert_sanitized(exc: AgentExecutionError) -> None:
    exposed = f"{exc!s} {exc!r} {vars(exc)!r}"
    assert "private-provider-model" not in exposed
    assert "sk-secret-upstream-detail" not in exposed


@pytest.mark.parametrize("status_code", [408, 504])
async def test_gateway_timeout_status_is_product_safe(status_code: int) -> None:
    mapped = await _execute_raising(
        ModelHTTPError(
            status_code=status_code,
            model_name="private-provider-model",
            body={"error": "sk-secret-upstream-detail"},
        )
    )

    assert mapped.code == "MODEL_TIMEOUT"
    assert mapped.retryable is True
    _assert_sanitized(mapped)


async def test_sdk_timeout_hidden_by_pydantic_ai_is_product_safe() -> None:
    request = httpx.Request("POST", "https://private-provider.invalid")
    sdk_timeout = APITimeoutError(request)
    provider_error = ModelAPIError(
        model_name="private-provider-model",
        message=_RAW_PROVIDER_DETAILS,
    )
    provider_error.__cause__ = sdk_timeout

    mapped = await _execute_raising(provider_error)

    assert mapped.code == "MODEL_TIMEOUT"
    assert mapped.retryable is True
    _assert_sanitized(mapped)


async def test_gateway_rate_limit_is_product_safe() -> None:
    mapped = await _execute_raising(
        ModelHTTPError(
            status_code=429,
            model_name="private-provider-model",
            body={"error": "sk-secret-upstream-detail"},
        )
    )

    assert mapped.code == "MODEL_RATE_LIMITED"
    assert mapped.retryable is True
    _assert_sanitized(mapped)


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [(401, False), (503, True)],
)
async def test_gateway_unavailable_is_product_safe(
    status_code: int,
    retryable: bool,
) -> None:
    mapped = await _execute_raising(
        ModelHTTPError(
            status_code=status_code,
            model_name="private-provider-model",
            body={"error": "sk-secret-upstream-detail"},
        )
    )

    assert mapped.code == "MODEL_UNAVAILABLE"
    assert mapped.retryable is retryable
    _assert_sanitized(mapped)


async def test_gateway_connection_failure_is_product_safe() -> None:
    mapped = await _execute_raising(
        ModelAPIError(
            model_name="private-provider-model",
            message=_RAW_PROVIDER_DETAILS,
        )
    )

    assert mapped.code == "MODEL_UNAVAILABLE"
    assert mapped.retryable is True
    _assert_sanitized(mapped)
