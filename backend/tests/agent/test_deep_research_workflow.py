"""Deterministic contracts for the v8 parallel Deep Research architecture."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from pydantic_ai_harness.dynamic_workflow import DynamicWorkflow, DynamicWorkflowToolset

from app.agent.capabilities.travel import build_travel_capabilities
from app.agent.subagents.research_worker import (
    EvidenceClaim,
    EvidenceSource,
    ImageAsset,
    ResearchFindings,
)
from app.agent.tools.research_tools import build_research_tools
from app.core.config import settings


def _ctx() -> RunContext[object]:
    return RunContext[object](
        deps=None,
        model=TestModel(),
        usage=RunUsage(),
        prompt=None,
        messages=[],
        run_step=1,
    )


async def _run_script(toolset: DynamicWorkflowToolset[object], code: str) -> object:
    ctx = _ctx()
    tools = await toolset.get_tools(ctx)
    tool = tools[toolset.tool_name]
    return await toolset.call_tool(toolset.tool_name, {"code": code}, ctx, tool)


def _noop(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    del messages, info
    return ModelResponse(parts=[TextPart("ok")])


def test_production_deep_research_config_is_bounded_and_deferred() -> None:
    capabilities = build_travel_capabilities(researcher_model=FunctionModel(_noop))
    workflow = next(item for item in capabilities if isinstance(item, DynamicWorkflow))

    assert workflow.id == "deep-research"
    assert workflow.tool_name == "run_workflow"
    assert workflow.defer_loading is True
    assert workflow.max_agent_calls == 3
    # Deliberate: each worker has independent 8/18 limits and does not consume
    # Main's small 8/6 role budget through a shared RunUsage counter.
    assert workflow.forward_usage is False
    assert workflow.resource_limits == {"max_duration_secs": 5}
    assert workflow.sub_agent_usage_limits is not None
    assert (
        workflow.sub_agent_usage_limits.request_limit
        == settings.RESEARCH_WORKER_MODEL_REQUEST_LIMIT
        == 8
    )
    assert (
        workflow.sub_agent_usage_limits.tool_calls_limit
        == settings.RESEARCH_WORKER_TOOL_CALL_LIMIT
        == 18
    )
    assert len(workflow.agents) == 1
    assert workflow.agents[0].name == "research_worker"


def test_research_worker_uses_only_shared_research_tools() -> None:
    names = {tool.name for tool in build_research_tools()}
    assert names == {
        "web_fetch",
        "search_maps",
        "get_weather",
    }
    assert "run_workflow" not in names
    assert "calculate_budget" not in names
    assert "convert_currency" not in names
    assert "load_capability" not in names


def test_verified_claim_requires_real_evidence() -> None:
    with pytest.raises(ValidationError, match="verified claims require"):
        EvidenceClaim(claim="故宫当前需要预约", status="verified")

    weather = EvidenceClaim(
        claim="旅行日期有降雨风险",
        status="verified",
        tool_evidence=["get_weather"],
    )
    assert weather.status == "verified"



def test_poi_media_is_structured_and_not_fact_evidence() -> None:
    asset = ImageAsset(
        place_name="故宫",
        image_url="https://images.example/palace.jpg",
        thumbnail_url="https://images.example/palace-thumb.jpg",
        source_page_url="https://photos.example/palace",
        title="故宫外观",
        width=1600,
        height=900,
        source="photos.example",
    )
    findings = ResearchFindings(topic="故宫视觉素材", media=[asset])

    assert findings.media[0].place_name == "故宫"
    assert findings.media[0].source_page_url == "https://photos.example/palace"
    with pytest.raises(ValidationError, match="verified claims require"):
        EvidenceClaim(
            claim="故宫明天开放",
            status="verified",
            # A media source page is deliberately not accepted as factual evidence.
        )

def test_verified_web_url_must_be_declared_as_source() -> None:
    claim = EvidenceClaim(
        claim="官方页面显示当前预约规则",
        status="verified",
        source_urls=["https://official.example/rule"],
    )
    with pytest.raises(ValidationError, match="missing from sources"):
        ResearchFindings(topic="预约", claims=[claim])

    findings = ResearchFindings(
        topic="预约",
        claims=[claim],
        sources=[
            EvidenceSource(
                title="Official rule",
                url="https://official.example/rule",
                source_type="official",
            )
        ],
    )
    assert findings.claims[0].status == "verified"


async def test_dynamic_workflow_really_overlaps_two_worker_runs() -> None:
    entered = 0
    both_entered = asyncio.Event()
    release = asyncio.Event()

    async def child_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del messages, info
        nonlocal entered
        entered += 1
        if entered == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=1)
        await asyncio.wait_for(release.wait(), timeout=1)
        return ModelResponse(parts=[TextPart("ok")])

    worker = Agent(FunctionModel(child_model), name="research_worker")
    workflow = DynamicWorkflow[object](agents=[worker], max_agent_calls=3)

    run = asyncio.create_task(
        _run_script(
            workflow.get_toolset(),
            """import asyncio
results = await asyncio.gather(
    research_worker(task="topic-a"),
    research_worker(task="topic-b"),
)
results""",
        )
    )

    await asyncio.wait_for(both_entered.wait(), timeout=1)
    assert entered == 2
    release.set()
    assert await asyncio.wait_for(run, timeout=1) == ["ok", "ok"]


async def test_worker_runs_have_isolated_message_history() -> None:
    transcripts: list[str] = []

    async def child_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        text = repr(messages)
        transcripts.append(text)
        return ModelResponse(parts=[TextPart("ok")])

    worker = Agent(FunctionModel(child_model), name="research_worker")
    workflow = DynamicWorkflow[object](agents=[worker], max_agent_calls=3)
    result = await _run_script(
        workflow.get_toolset(),
        """import asyncio
results = await asyncio.gather(
    research_worker(task="ONLY_A_SECRET"),
    research_worker(task="ONLY_B_SECRET"),
)
results""",
    )

    assert result == ["ok", "ok"]
    assert len(transcripts) == 2
    a = next(item for item in transcripts if "ONLY_A_SECRET" in item)
    b = next(item for item in transcripts if "ONLY_B_SECRET" in item)
    assert "ONLY_B_SECRET" not in a
    assert "ONLY_A_SECRET" not in b


async def test_safe_wrapper_preserves_partial_success_when_one_worker_fails() -> None:
    async def child_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        prompt = next(
            (
                part.content
                for message in messages
                for part in message.parts
                if isinstance(part, UserPromptPart) and isinstance(part.content, str)
            ),
            "",
        )
        if "FAIL_TOPIC" in prompt:
            raise RuntimeError("synthetic child failure")
        return ModelResponse(parts=[TextPart("success")])

    worker = Agent(FunctionModel(child_model), name="research_worker")
    workflow = DynamicWorkflow[object](agents=[worker], max_agent_calls=3, max_retries=1)
    result = await _run_script(
        workflow.get_toolset(),
        """import asyncio
async def safe(task):
    try:
        return await research_worker(task=task)
    except RuntimeError:
        return {"status": "unresolved", "task": task}
results = await asyncio.gather(
    safe("OK_TOPIC"),
    safe("FAIL_TOPIC"),
)
results""",
    )

    assert result[0] == "success"  # type: ignore[index]
    assert result[1]["status"] == "unresolved"  # type: ignore[index]


async def test_dynamic_workflow_hard_caps_fourth_worker_call() -> None:
    worker = Agent(TestModel(custom_output_text="ok"), name="research_worker")
    workflow = DynamicWorkflow[object](agents=[worker], max_agent_calls=3, max_retries=1)
    result = await _run_script(
        workflow.get_toolset(),
        """a = await research_worker(task="1")
b = await research_worker(task="2")
c = await research_worker(task="3")
d = await research_worker(task="4")
[a, b, c, d]""",
    )

    rendered = repr(result)
    assert "sub-agent call budget (3)" in rendered or "exhausted" in rendered
