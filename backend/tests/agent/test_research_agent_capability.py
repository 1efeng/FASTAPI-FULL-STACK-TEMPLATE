"""Main-to-research_agent handoff boundary tests."""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agent.capabilities.research_agent import (
    RESEARCH_AGENT_CAPABILITY_ID,
    RESEARCH_AGENT_TOOL_NAME,
    build_research_agent_capability,
)
from app.agent.research_runtime import (
    ResearchRequestState,
    bind_research_request_state,
)


def _final(info: AgentInfo, payload: dict[str, Any]) -> ModelResponse:
    assert info.output_tools
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args=payload,
                tool_call_id="research-final",
            )
        ]
    )


def _tool_returns(messages: list[ModelMessage], name: str) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == name
    ]


async def test_main_receives_only_compressed_research_findings() -> None:
    child_prompts: list[str] = []

    def child_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        user_text = str(messages[0])
        child_prompts.append(user_text)
        return _final(
            info,
            {
                "topic": "东京到箱根交通比较",
                "summary": "当前证据支持方案 A；儿童政策仍需确认。",
                "claims": [],
                "sources": [],
                "media": [],
                "unresolved": ["儿童政策"],
            },
        )

    parent_seen_returns: list[ToolReturnPart] = []

    def parent_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returns = _tool_returns(messages, RESEARCH_AGENT_TOOL_NAME)
        if not returns:
            assert any(tool.name == RESEARCH_AGENT_TOOL_NAME for tool in info.function_tools)
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=RESEARCH_AGENT_TOOL_NAME,
                        args={
                            "objective": "比较东京到箱根交通 Pass",
                            "context": "Candidate Plan: Day 2 前往箱根",
                            "constraints": ["2 adults", "1 child"],
                        },
                        tool_call_id="delegate-research",
                    )
                ]
            )
        parent_seen_returns.extend(returns)
        return ModelResponse(parts=[TextPart("采用方案 A")])

    capability = build_research_agent_capability(model=FunctionModel(child_model))
    assert capability.id == RESEARCH_AGENT_CAPABILITY_ID

    main = Agent(FunctionModel(parent_model), capabilities=(capability,))
    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await main.run("做一个候选计划后比较箱根交通")

    assert result.output == "采用方案 A"
    assert len(parent_seen_returns) == 1
    returned = str(parent_seen_returns[0].content)
    assert "东京到箱根交通比较" in returned
    assert "儿童政策" in returned
    assert child_prompts
    prompt = child_prompts[0]
    assert "比较东京到箱根交通 Pass" in prompt
    assert "Candidate Plan: Day 2 前往箱根" in prompt
    assert "2 adults" in prompt
    assert state.research_requests > 0
    # Separate child usage is collected for Product accounting rather than being
    # folded into Main's own RunUsage counter.
    assert result.usage.requests == 2
    assert state.research_requests == 1
