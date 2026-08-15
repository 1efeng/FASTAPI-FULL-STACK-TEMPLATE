"""H1 trajectory tests: Optional Researcher / Research Need routing.

Proves, through the real capability wiring (``build_travel_capabilities``) with
scripted FunctionModel parents, that every legal trajectory is supported and
that the Researcher delegation budget (``max_calls=1``) stays enforced:

- Research Need NO -> Main plans directly; ``delegate_task`` is never called.
- Research Need YES -> ``delegate_task`` runs exactly once.
- Researcher failure / timeout -> no second delegation; Main degrades gracefully.
- Casual chat and ordinary travel Q&A never load the planning Skill or delegate.

No provider is ever contacted: search/weather/route/currency backends are
isolated with deterministic fakes via autouse fixtures.
"""

import asyncio
from collections.abc import Callable
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agent.capabilities.travel import (
    RESEARCHER_ON_FAILURE_MESSAGE,
    build_travel_capabilities,
)
from app.agent.tools.search_providers.fake import FakeSearchProvider
from app.core.config import settings

_DELEGATE = "delegate_task"
_RESEARCHER = "travel-researcher"
_SKILL_PLANNING = "travel-planning"


def _delegate_part(tool_call_id: str, task: str) -> ToolCallPart:
    return ToolCallPart(
        tool_name=_DELEGATE,
        args={"agent_name": _RESEARCHER, "task": task},
        tool_call_id=tool_call_id,
    )


def _load_skill_part(
    tool_call_id: str, skill_id: str = _SKILL_PLANNING
) -> ToolCallPart:
    return ToolCallPart(
        tool_name="load_capability",
        args={"id": skill_id},
        tool_call_id=tool_call_id,
    )


def _tool_calls(
    messages: list[ModelMessage], tool_name: str
) -> int:
    return sum(
        1
        for message in messages
        for part in message.parts
        if isinstance(part, ToolCallPart) and part.tool_name == tool_name
    )


def _tool_returns(
    messages: list[ModelMessage], tool_name: str
) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == tool_name
    ]


def _delegate_returns(messages: list[ModelMessage]) -> list[str]:
    return [str(part.content) for part in _tool_returns(messages, _DELEGATE)]


def _noop_child(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    del messages, info
    return ModelResponse(parts=[TextPart("ok")])


def _raise_missing() -> str:
    raise RuntimeError("missing")


def _fake_provider() -> FakeSearchProvider:
    return FakeSearchProvider()


@pytest.fixture(autouse=True)
def _isolate_external_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every trajectory offline and deterministic."""
    monkeypatch.setattr(
        "app.agent.tools.search.get_search_provider", _fake_provider
    )
    monkeypatch.setattr("app.agent.tools.weather._weather_api_key", _raise_missing)
    monkeypatch.setattr("app.agent.tools.route.require_tool_key", _raise_missing)
    monkeypatch.setattr(
        "app.agent.tools.currency.get_exchange_rate",
        AsyncMock(return_value=(Decimal("0.05"), "2026-08-14", "fake")),
    )


def _agent(
    parent_model: Callable[[list[ModelMessage], AgentInfo], ModelResponse],
    researcher_model: Callable[[list[ModelMessage], AgentInfo], ModelResponse],
) -> Agent[object, str]:
    return Agent(
        FunctionModel(parent_model),
        capabilities=build_travel_capabilities(
            researcher_model=FunctionModel(researcher_model),
        ),
    )


# ---------------------------------------------------------------------------
# CASE 1: casual chat — no Skill load, no delegation
# ---------------------------------------------------------------------------


async def test_case1_casual_chat_never_loads_skill_or_delegates() -> None:
    def parent_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del messages, info
        return ModelResponse(parts=[TextPart("你好呀！有什么可以帮你？")])

    agent = _agent(parent_model, _noop_child)
    result = await agent.run("你好")

    assert result.output == "你好呀！有什么可以帮你？"
    messages = result.all_messages()
    assert _tool_calls(messages, _DELEGATE) == 0
    assert _tool_calls(messages, "load_capability") == 0
    assert _tool_calls(messages, "search_web") == 0
    assert _tool_calls(messages, "get_weather") == 0


# ---------------------------------------------------------------------------
# CASE 2: ordinary travel fact — Main calls get_weather directly, no delegate
# ---------------------------------------------------------------------------


async def test_case2_ordinary_fact_uses_main_tool_without_delegation() -> None:
    def parent_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        if _tool_returns(messages, "get_weather"):
            return ModelResponse(parts=[TextPart("东京明天多云转晴。")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="get_weather",
                    args={"city": "东京"},
                    tool_call_id="weather-1",
                )
            ]
        )

    agent = _agent(parent_model, _noop_child)
    result = await agent.run("东京明天天气怎么样")

    assert result.output == "东京明天多云转晴。"
    messages = result.all_messages()
    assert _tool_calls(messages, _DELEGATE) == 0
    assert _tool_calls(messages, "get_weather") == 1
    assert _tool_calls(messages, "load_capability") == 0


# ---------------------------------------------------------------------------
# CASE 2b: ordinary fact — Main can use search_web directly, no delegate
# ---------------------------------------------------------------------------


async def test_case2b_ordinary_fact_can_use_search_web_without_delegation() -> None:
    def parent_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        if _tool_returns(messages, "search_web"):
            return ModelResponse(parts=[TextPart("浅草寺通常 17:00 关门。")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="search_web",
                    args={"query": "浅草寺 关门时间"},
                    tool_call_id="search-1",
                )
            ]
        )

    agent = _agent(parent_model, _noop_child)
    result = await agent.run("浅草寺几点关门")

    assert result.output == "浅草寺通常 17:00 关门。"
    messages = result.all_messages()
    assert _tool_calls(messages, _DELEGATE) == 0
    assert _tool_calls(messages, "search_web") == 1
    assert _tool_calls(messages, "load_capability") == 0


# ---------------------------------------------------------------------------
# CASE 3: rough draft plan (Research Need NO) — Skill + budget, no delegate
# ---------------------------------------------------------------------------


async def test_case3_rough_plan_no_research_need_never_delegates() -> None:
    def parent_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        if _tool_returns(messages, "calculate_budget"):
            return ModelResponse(
                parts=[TextPart("# 东京3日旅行计划\n\n## Day 1｜浅草·上野")]
            )
        if _tool_returns(messages, "load_capability"):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="calculate_budget",
                        args={
                            "currency": "JPY",
                            "people": 2,
                            "items": [
                                {
                                    "name": "城际交通",
                                    "category": "transport",
                                    "amount_min": "14000",
                                    "quantity": 1,
                                    "per_person": True,
                                }
                            ],
                        },
                        tool_call_id="budget-1",
                    )
                ]
            )
        return ModelResponse(parts=[_load_skill_part("load-1")])

    agent = _agent(parent_model, _noop_child)
    result = await agent.run("先大概帮我排一下东京三天的框架")

    assert "# 东京3日旅行计划" in result.output
    messages = result.all_messages()
    assert _tool_calls(messages, _DELEGATE) == 0
    assert _tool_calls(messages, "load_capability") == 1
    assert _tool_calls(messages, "calculate_budget") == 1


# ---------------------------------------------------------------------------
# CASE 4: inspiration (Research Need NO) — Skill + FX, no delegate
# ---------------------------------------------------------------------------


async def test_case4_inspiration_no_research_need_never_delegates() -> None:
    def parent_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        if _tool_returns(messages, "convert_currency"):
            return ModelResponse(
                parts=[TextPart("北京三日游思路：D1 故宫—景山，D2 长城，D3 胡同。")]
            )
        if _tool_returns(messages, "load_capability"):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="convert_currency",
                        args={
                            "from_currency": "JPY",
                            "amounts": [{"name": "预算参考", "amount_min": "10000"}],
                        },
                        tool_call_id="fx-1",
                    )
                ]
            )
        return ModelResponse(parts=[_load_skill_part("load-1")])

    agent = _agent(parent_model, _noop_child)
    result = await agent.run("给我一个北京三日游思路")

    assert "北京三日游思路" in result.output
    messages = result.all_messages()
    assert _tool_calls(messages, _DELEGATE) == 0
    assert _tool_calls(messages, "load_capability") == 1
    assert _tool_calls(messages, "convert_currency") == 1


# ---------------------------------------------------------------------------
# CASE 5: executable / current-fact plan (Research Need YES) — exactly one delegate
# ---------------------------------------------------------------------------


async def test_case5_executable_plan_delegates_exactly_once() -> None:
    child_calls = 0

    def child_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del messages, info
        nonlocal child_calls
        child_calls += 1
        return ModelResponse(
            parts=[
                TextPart(
                    "Research Findings：\n"
                    "- 开放：浅草寺 6:00-17:00\n"
                    "- 新干线 东京—京都 JPY 14,000"
                )
            ]
        )

    def parent_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        if _delegate_returns(messages):
            return ModelResponse(parts=[TextPart("# 东京京都5日旅行计划")])
        return ModelResponse(
            parts=[
                _delegate_part(
                    "delegate-1",
                    "自包含 Research Brief：Runtime 2026-08-15；东京京都5日；开放时间/门票/交通。",
                )
            ]
        )

    agent = _agent(parent_model, child_model)
    result = await agent.run("按实际情况规划东京京都5日")

    assert result.output == "# 东京京都5日旅行计划"
    messages = result.all_messages()
    assert _tool_calls(messages, _DELEGATE) == 1
    assert child_calls == 1
    assert _delegate_returns(messages)[0].startswith("Research Findings")


# ---------------------------------------------------------------------------
# CASE 6: explicit verification request (Research Need YES) — exactly one delegate
# ---------------------------------------------------------------------------


async def test_case6_explicit_verification_delegates_exactly_once() -> None:
    child_calls = 0

    def child_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del messages, info
        nonlocal child_calls
        child_calls += 1
        return ModelResponse(parts=[TextPart("Research Findings：核实完成。")])

    def parent_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        if _delegate_returns(messages):
            return ModelResponse(parts=[TextPart("已按核实结果更新计划。")])
        return ModelResponse(
            parts=[
                _delegate_part(
                    "delegate-1",
                    "自包含 Research Brief：确认预约规则与最新开放时间。",
                )
            ]
        )

    agent = _agent(parent_model, child_model)
    result = await agent.run("帮我查官方确认一下预约规则再规划")

    assert result.output == "已按核实结果更新计划。"
    messages = result.all_messages()
    assert _tool_calls(messages, _DELEGATE) == 1
    assert child_calls == 1


# ---------------------------------------------------------------------------
# CASE 7: researcher timeout -> steering, no second delegation, marked unverified
# ---------------------------------------------------------------------------


async def test_case7_researcher_failure_no_second_delegation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "TRAVEL_RESEARCHER_TIMEOUT_SECONDS", 0.05)
    child_calls = 0

    async def slow_child(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del messages, info
        nonlocal child_calls
        child_calls += 1
        try:
            await asyncio.get_running_loop().create_future()
        except asyncio.CancelledError:
            raise
        raise AssertionError("child returned after timeout")

    def parent_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        if _delegate_returns(messages):
            return ModelResponse(
                parts=[TextPart("最终计划（部分事实未核实，建议执行前确认）。")]
            )
        return ModelResponse(
            parts=[_delegate_part("delegate-1", "自包含 Research Brief。")]
        )

    agent = _agent(parent_model, slow_child)
    result = await agent.run("按最新情况规划")

    assert "未核实" in result.output
    messages = result.all_messages()
    assert _tool_calls(messages, _DELEGATE) == 1
    assert child_calls == 1
    assert _delegate_returns(messages) == [RESEARCHER_ON_FAILURE_MESSAGE]


# ---------------------------------------------------------------------------
# CASE 8: simple modification (Research Need NO) — no delegate, keep constraints
# ---------------------------------------------------------------------------


async def test_case8_simple_modification_no_delegate_keeps_constraints() -> None:
    history = [
        ModelRequest(
            parts=[
                UserPromptPart(
                    "已有完整计划：\n"
                    "# 京都大阪5日旅行计划\n"
                    "## Day 1｜京都 清水寺\n"
                    "## Day 2｜大阪 道顿堀\n"
                    "约束：住宿京都站附近；不赶行程。"
                )
            ]
        )
    ]

    def parent_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        if _tool_returns(messages, "load_capability"):
            return ModelResponse(
                parts=[
                    TextPart(
                        "# 京都大阪5日旅行计划\n"
                        "## Day 2｜奈良 东大寺\n"
                        "保留：住宿京都站附近；不赶行程。"
                    )
                ]
            )
        return ModelResponse(parts=[_load_skill_part("load-1")])

    agent = _agent(parent_model, _noop_child)
    result = await agent.run(
        "把第二天改成奈良，不用查最新", message_history=history
    )

    assert "奈良" in result.output
    assert "住宿京都站附近" in result.output
    messages = result.all_messages()
    assert _tool_calls(messages, _DELEGATE) == 0


# ---------------------------------------------------------------------------
# CASE 9: fresh-fact modification (Research Need YES) — exactly one delegate
# ---------------------------------------------------------------------------


async def test_case9_fresh_fact_modification_delegates_once() -> None:
    child_calls = 0

    def child_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del messages, info
        nonlocal child_calls
        child_calls += 1
        return ModelResponse(
            parts=[TextPart("Research Findings：当日闭馆，改为隔日。")]
        )

    def parent_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        if _delegate_returns(messages):
            return ModelResponse(parts=[TextPart("已按最新闭馆日调整。")])
        return ModelResponse(
            parts=[
                _delegate_part(
                    "delegate-1",
                    "自包含 Research Brief：核验修改后的开放/闭馆日。",
                )
            ]
        )

    history = [
        ModelRequest(parts=[UserPromptPart("已有完整计划：# 东京5日旅行计划")])
    ]
    agent = _agent(parent_model, child_model)
    result = await agent.run(
        "把第二天改成周一去的景点，查一下最新闭馆日",
        message_history=history,
    )

    assert result.output == "已按最新闭馆日调整。"
    messages = result.all_messages()
    assert _tool_calls(messages, _DELEGATE) == 1
    assert child_calls == 1


# ---------------------------------------------------------------------------
# CASE 10: max_calls=1 enforced by the real wiring even if Main re-delegates
# ---------------------------------------------------------------------------


async def test_case10_max_calls_1_blocks_second_delegation_in_real_wiring() -> None:
    child_calls = 0

    def child_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del messages, info
        nonlocal child_calls
        child_calls += 1
        return ModelResponse(parts=[TextPart("findings")])

    def parent_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        returns = _delegate_returns(messages)
        if len(returns) == 0:
            return ModelResponse(
                parts=[_delegate_part("delegate-1", "BRIEF")]
            )
        if len(returns) == 1:
            return ModelResponse(
                parts=[_delegate_part("delegate-2", "SUPPLEMENT_BRIEF")]
            )
        return ModelResponse(parts=[TextPart("final")])

    agent = _agent(parent_model, child_model)
    result = await agent.run("按最新情况规划")

    assert result.output == "final"
    messages = result.all_messages()
    # The model attempted two delegations; the runtime ran the child once and
    # soft-blocked the second with the on-failure steering message.
    assert _tool_calls(messages, _DELEGATE) == 2
    assert child_calls == 1
    assert _delegate_returns(messages) == ["findings", RESEARCHER_ON_FAILURE_MESSAGE]
