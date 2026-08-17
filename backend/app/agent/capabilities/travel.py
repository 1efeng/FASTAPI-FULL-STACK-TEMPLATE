"""Travel capability composition and Skill-to-Tool dependency validation."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path

from pydantic_ai import Tool, UsageLimits, WebSearchTool
from pydantic_ai.capabilities import AgentCapability, Capability, WebSearch
from pydantic_ai.models import KnownModelName, Model
from pydantic_ai_harness.dynamic_workflow import DynamicWorkflow
from pydantic_ai_harness.skills import Skills

from app.agent.capabilities.research_guard import SingleWorkflowCallGate
from app.agent.subagents.research_worker import build_research_worker
from app.agent.tools.budget import calculate_budget
from app.agent.tools.currency import convert_currency
from app.agent.tools.research_tools import build_research_tools
from app.core.config import settings

SKILL_LIBRARY = Path(__file__).resolve().parents[1] / "skills"
_DEEP_RESEARCH_TOOL_NAME = "run_workflow"

# Skills contain instructions only. Every executable dependency stays explicit and
# is validated before the capability bundle can reach a model.
SKILL_TOOL_DEPENDENCIES: Mapping[str, frozenset[str]] = {
    "travel-budget": frozenset({"calculate_budget"}),
    "travel-planning": frozenset(
        {
            "web_fetch",
            "search_maps",
            "get_weather",
            "calculate_budget",
            "convert_currency",
            _DEEP_RESEARCH_TOOL_NAME,
        }
    ),
}

_BUDGET_TOOL = Tool[object](calculate_budget, takes_ctx=False)
_CURRENCY_TOOL = Tool[object](convert_currency, takes_ctx=False)
_MAIN_TOOLS: tuple[Tool[object], ...] = (
    *build_research_tools(),
    _BUDGET_TOOL,
    _CURRENCY_TOOL,
)


def validate_skill_tool_dependencies(
    *,
    selected_skills: Collection[str],
    available_tools: Collection[str],
) -> None:
    """Fail closed when a selected Skill references an unavailable Tool."""
    available = frozenset(available_tools)
    for skill_name in selected_skills:
        required = SKILL_TOOL_DEPENDENCIES.get(skill_name)
        if required is None:
            raise ValueError(f"Skill 未声明 Tool 依赖：{skill_name}")
        missing = required - available
        if missing:
            missing_names = ", ".join(sorted(missing))
            raise ValueError(f"Skill {skill_name} 缺少 Tool：{missing_names}")


def build_travel_capabilities(
    *,
    researcher_model: Model | KnownModelName | str | None = None,
    enable_planning_core: bool = True,
    enable_web_search: bool = True,
) -> tuple[AgentCapability[object], ...]:
    """Build Main tools, Skills, and the optional parallel Deep Research capability.

    ``researcher_model`` is retained as the composition-root argument name for
    compatibility with the current executor; it now configures ``research_worker``.
    """
    selected_skills = (
        frozenset(SKILL_TOOL_DEPENDENCIES)
        if enable_planning_core and enable_web_search
        else frozenset({"travel-budget"})
    )
    active_tools = (
        _MAIN_TOOLS if enable_planning_core and enable_web_search else (_BUDGET_TOOL,)
    )
    available_tools = {tool.name for tool in active_tools}
    if enable_planning_core and enable_web_search:
        available_tools.add(_DEEP_RESEARCH_TOOL_NAME)
    validate_skill_tool_dependencies(
        selected_skills=selected_skills,
        available_tools=available_tools,
    )

    skill_catalog = Skills[object](SKILL_LIBRARY, include=selected_skills)
    main_tools = Capability[object](id="travel-main-tools", tools=active_tools)
    if not enable_web_search:
        return (skill_catalog, main_tools)

    native_web_search = WebSearch(native=WebSearchTool(optional=True))
    if not enable_planning_core:
        return (skill_catalog, native_web_search, main_tools)

    research_worker = build_research_worker(model=researcher_model)
    workflow_gate = SingleWorkflowCallGate(tool_name=_DEEP_RESEARCH_TOOL_NAME)
    deep_research = DynamicWorkflow[object](
        agents=(research_worker,),
        id="deep-research",
        description=(
            "Parallel Deep Research for 2-3 independent travel fact topics; "
            "returns only compact structured findings to Main."
        ),
        defer_loading=True,
        max_agent_calls=3,
        # Keep Main's 8/6 UsageLimits independent from child loops. Harness 0.21
        # uses the parent's shared usage counter when forward_usage=True, which
        # would make child requests/tool calls consume Main's small role budget.
        forward_usage=False,
        inherit_model=False,
        # Monty CPU guard only; time awaiting sub-agents is intentionally not counted.
        resource_limits={"max_duration_secs": 5},
        sub_agent_usage_limits=UsageLimits(
            request_limit=settings.RESEARCH_WORKER_MODEL_REQUEST_LIMIT,
            tool_calls_limit=settings.RESEARCH_WORKER_TOOL_CALL_LIMIT,
        ),
    )
    return (skill_catalog, native_web_search, main_tools, workflow_gate, deep_research)
