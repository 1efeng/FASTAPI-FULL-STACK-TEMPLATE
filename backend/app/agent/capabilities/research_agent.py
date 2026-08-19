"""High-level Main capability that delegates one context-collection research topic."""

from __future__ import annotations

from pydantic_ai import Tool, UsageLimits
from pydantic_ai.capabilities import Capability
from pydantic_ai.exceptions import (
    ModelAPIError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.models import KnownModelName, Model
from pydantic_ai_harness.dynamic_workflow import DynamicWorkflow

from app.agent.agents.research_agent import (
    ResearchFindings,
    ResearchRequest,
    build_research_agent,
)
from app.core.config import settings

RESEARCH_AGENT_TOOL_NAME = "research_agent"
RESEARCH_AGENT_CAPABILITY_ID = "travel-research-agent"
RESEARCH_WORKFLOW_CAPABILITY_ID = "travel-research-workflow"


def build_research_agent_capability(
    *,
    model: Model | KnownModelName | str | None,
) -> Capability[object]:
    """Expose ``research_agent`` to Main as a context-collection child-agent tool.

    The child only searches + summarizes context for Main; it never verifies,
    grades, or proves any fact. Main may issue multiple independent calls in one
    model turn; PydanticAI executes them concurrently because this tool is
    non-sequential.
    """

    agent = build_research_agent(model=model)

    async def research_agent(
        objective: str,
        title: str | None = None,
        context: str | None = None,
        constraints: list[str] | None = None,
    ) -> ResearchFindings:
        """Search and summarize enough context for one travel planning topic."""
        request = ResearchRequest(
            objective=objective,
            title=title,
            context=context,
            constraints=constraints or [],
        )
        try:
            result = await agent.run(
                request.model_dump_json(exclude_none=True),
                usage_limits=UsageLimits(
                    request_limit=settings.RESEARCH_AGENT_MODEL_REQUEST_LIMIT,
                    tool_calls_limit=settings.RESEARCH_AGENT_TOOL_CALL_LIMIT,
                ),
            )
            return result.output
        except (ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded):
            # One independent research topic must not abort sibling topics or the
            # whole Main plan when the child provider/output fails.
            return ResearchFindings(
                topic=request.objective,
                summary="当前主题未能搜索到足够上下文。",
            )

    tool = Tool[object](
        research_agent,
        takes_ctx=False,
        name=RESEARCH_AGENT_TOOL_NAME,
        sequential=False,
        description=(
            "Search and summarize enough context for one travel planning topic. "
            "Use it when Main needs background that would otherwise bloat its "
            "context. It never verifies or proves facts; it only collects context."
        ),
    )
    return Capability[object](
        id=RESEARCH_AGENT_CAPABILITY_ID,
        description="Context collection for Main via a bounded search + summarize child agent.",
        tools=(tool,),
    )


def build_research_workflow_capability(
    *,
    model: Model | KnownModelName | str | None,
) -> DynamicWorkflow:
    """Build the legacy workflow path kept only for rollback/compatibility.

    Production Travel composition uses ``build_research_agent_capability`` directly.
    Keeping this builder isolated preserves a low-risk rollback path without exposing
    two competing research orchestration tools to Main at the same time.
    """

    research_agent = build_research_agent(model=model)
    return DynamicWorkflow(
        id=RESEARCH_WORKFLOW_CAPABILITY_ID,
        description=(
            "Fan out independent travel research topics, then return their findings "
            "for Main to revise the plan."
        ),
        agents=(research_agent,),
        tool_name="run_workflow",
        max_agent_calls=2,
        sub_agent_usage_limits=UsageLimits(
            request_limit=settings.RESEARCH_AGENT_MODEL_REQUEST_LIMIT,
            tool_calls_limit=settings.RESEARCH_AGENT_TOOL_CALL_LIMIT,
        ),
        forward_usage=False,
    )