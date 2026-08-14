import importlib.metadata
import json
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart, ThinkingPart
from pydantic_ai.models.test import TestModel

from app.agent.executor import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentStreamTerminalKind,
)
from app.agent.pydantic_executor import (
    VERCEL_AI_SDK_VERSION,
    _to_reasoning_summary,
    stream_vercel_events,
)

_REQUEST_ID = UUID("11111111-1111-4111-8111-111111111111")
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "vercel_ai_sdk_v7_text_stream.json"
)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _decode_sse_chunks(chunks: list[str]) -> list[dict[str, Any] | str]:
    events: list[dict[str, Any] | str] = []
    text_part_id: str | None = None

    for chunk in chunks:
        assert chunk.startswith("data: ")
        assert chunk.endswith("\n\n")
        data = chunk.removeprefix("data: ").removesuffix("\n\n")
        if data == "[DONE]":
            events.append(data)
            continue

        event = json.loads(data)
        assert isinstance(event, dict)
        event_type = event.get("type")
        if event_type == "text-start":
            text_part_id = event["id"]
        if event_type in {"text-start", "text-delta", "text-end"}:
            assert event["id"] == text_part_id
            event["id"] = "<text-part-id>"
        if event_type == "message-metadata":
            event["messageMetadata"]["pydantic_ai"]["timestamp"] = "<timestamp>"
        events.append(event)

    return events


def _load_fixture() -> dict[str, Any]:
    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(fixture, dict)
    return fixture


def test_protocol_pair_is_exactly_pinned() -> None:
    fixture_versions = _load_fixture()["versions"]
    backend_manifest = tomllib.loads(
        (_REPOSITORY_ROOT / "backend" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    frontend_manifest = json.loads(
        (_REPOSITORY_ROOT / "frontend" / "package.json").read_text(
            encoding="utf-8"
        )
    )

    assert f"pydantic-ai=={fixture_versions['pydantic-ai']}" in (
        backend_manifest["project"]["dependencies"]
    )
    assert (
        frontend_manifest["dependencies"]["ai"] == fixture_versions["ai"]
    )
    assert frontend_manifest["dependencies"]["@ai-sdk/react"] == (
        fixture_versions["@ai-sdk/react"]
    )
    assert importlib.metadata.version("pydantic-ai") == (
        fixture_versions["pydantic-ai"]
    )
    assert VERCEL_AI_SDK_VERSION == fixture_versions["sdk_version"]


def test_public_reasoning_summary_excludes_provider_metadata() -> None:
    class FakeResult:
        def new_messages(self):
            return [
                ModelResponse(
                    parts=[
                        ThinkingPart(
                            content="  compare routes  ",
                            id="provider-part-id",
                            signature="must-not-be-persisted",
                            provider_name="test-provider",
                            provider_details={"private": "metadata"},
                        ),
                        TextPart(content="final"),
                        ThinkingPart(content="check budget"),
                    ]
                )
            ]

    assert _to_reasoning_summary(cast(Any, FakeResult())) == (
        "compare routes\n\ncheck budget"
    )


async def test_adapter_v7_text_stream_matches_protocol_fixture() -> None:
    request = AgentExecutionRequest(
        request_id=_REQUEST_ID,
        conversation_id=UUID("22222222-2222-4222-8222-222222222222"),
        message="hello",
        history=(),
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    agent = Agent(TestModel(custom_output_text="fixture answer"))

    with patch("app.agent.pydantic_executor.get_chat_agent", return_value=agent):
        chunks = [chunk async for chunk in stream_vercel_events(request)]

    assert _decode_sse_chunks(chunks) == _load_fixture()["events"]


async def test_adapter_terminal_chunks_are_held_for_product_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = AgentExecutionRequest(
        request_id=_REQUEST_ID,
        conversation_id=UUID("22222222-2222-4222-8222-222222222222"),
        message="hello",
        history=(),
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
    )

    class FakeAdapter:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def run_stream(self, **kwargs):
            del kwargs

            async def empty_events():
                return
                yield

            return empty_events()

        async def encode_stream(self, stream):
            del stream
            yield 'data: {"type":"text-delta","id":"part","delta":"x"}\n\n'
            yield 'data: {"type":"error","errorText":"unsafe provider detail"}\n\n'
            yield "data: [DONE]\n\n"

    observed: list[tuple[str, str | None]] = []

    async def on_terminal(
        kind: AgentStreamTerminalKind,
        reason: str | None,
    ) -> str:
        observed.append((kind, reason))
        return 'data: {"type":"error","errorText":"safe product error"}\n\n'

    monkeypatch.setattr(
        "app.agent.pydantic_executor.VercelAIAdapter",
        FakeAdapter,
    )
    chunks = [
        chunk
        async for chunk in stream_vercel_events(
            request,
            on_terminal=on_terminal,
        )
    ]

    assert chunks == [
        'data: {"type":"text-delta","id":"part","delta":"x"}\n\n',
        'data: {"type":"error","errorText":"safe product error"}\n\n',
        "data: [DONE]\n\n",
    ]
    assert observed == [("error", "unsafe provider detail")]


async def test_adapter_completion_projects_reasoning_into_product_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = AgentExecutionRequest(
        request_id=_REQUEST_ID,
        conversation_id=UUID("22222222-2222-4222-8222-222222222222"),
        message="hello",
        history=(),
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
    )

    class FakeResult:
        output = "final answer"

        class Usage:
            requests = 0
            tool_calls = 0

        usage = Usage()

        def new_messages(self):
            return [
                ModelResponse(
                    parts=[
                        ThinkingPart(content="public reasoning"),
                        TextPart(content="final answer"),
                    ]
                )
            ]

    class FakeAdapter:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def run_stream(self, **kwargs):
            callback = kwargs["on_complete"]

            async def events():
                yield "reasoning-start"
                yield "reasoning-end"
                await callback(cast(Any, FakeResult()))

            return events()

        async def encode_stream(self, stream):
            async for event in stream:
                if event == "reasoning-start":
                    yield 'data: {"type":"reasoning-start","id":"reasoning"}\n\n'
                elif event == "reasoning-end":
                    yield 'data: {"type":"reasoning-end","id":"reasoning"}\n\n'
            yield 'data: {"type":"finish"}\n\n'
            yield "data: [DONE]\n\n"

    completed: list[AgentExecutionResult] = []

    async def on_complete(result: AgentExecutionResult) -> None:
        completed.append(result)

    monkeypatch.setattr(
        "app.agent.pydantic_executor.VercelAIAdapter",
        FakeAdapter,
    )
    chunks = [
        chunk
        async for chunk in stream_vercel_events(
            request,
            on_complete=on_complete,
        )
    ]

    assert chunks[-1] == "data: [DONE]\n\n"
    assert len(completed) == 1
    assert completed[0].content == "final answer"
    assert completed[0].reasoning_summary == "public reasoning"
    assert completed[0].reasoning_duration_ms is not None
    assert completed[0].reasoning_duration_ms >= 1
