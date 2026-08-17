"""High-level Main capability that delegates one bounded research topic."""

from __future__ import annotations

from pydantic_ai import Tool, UsageLimits
from pydantic_ai.capabilities import Capability
from pydantic_ai.exceptions import ModelAPIError, UnexpectedModelBehavior
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


def _format_research_request(request: ResearchRequest) -> str:
    """Serialize only the explicit handoff contract into the child context."""
    return request.model_dump_json(exclude_none=True)


def build_research_agent_capability(
    *,
    model: Model | KnownModelName | str | None,
) -> Capability[object]:
    """Expose ``research_agent`` to Main as a topic-level child-agent tool.

    Each call investigates one coherent research topic discovered from a domain
    Skill's plan. Main may issue multiple independent calls in one model turn;
    PydanticAI can execute them concurrently because this tool is non-sequential.
    The child executes inline in the current Main tool await chain, so Product
    cancellation naturally propagates. Only ``ResearchFindings`` is returned to
    Main; the child model/tool trajectory remains inside the child run.
    """
    async def research_agent(
        objective: str,
        context: str | None = None,
        constraints: list[str] | None = None,
    ) -> ResearchFindings:
        """Investigate one bounded travel research topic and return evidence-backed findings."""
        request = ResearchRequest(
            objective=objective,
            context=context,
            constraints=constraints or [],
        )
        # Build one Agent graph per tool call. PydanticAI can execute multiple
        # non-sequential calls concurrently; sharing a mutable Agent graph risks
        # cross-call state and breaks the parallel handoff contract.
        research = build_research_agent(model=model)
        try:
            result = await research.run(
                _format_research_request(request),
                usage_limits=UsageLimits(
                    request_limit=settings.RESEARCH_AGENT_MODEL_REQUEST_LIMIT,
                    tool_calls_limit=settings.RESEARCH_AGENT_TOOL_CALL_LIMIT,
                ),
            )
        except (ModelAPIError, UnexpectedModelBehavior):
            # One independent research topic must not abort sibling topics or the
            # whole Main plan when the child provider/output fails recoverably.
            # Cancellation is BaseException and UsageLimitExceeded is intentionally
            # not caught, so runtime ownership and hard budgets still propagate.
            return ResearchFindings(
                topic=request.objective,
                unresolved=["当前研究主题暂时无法可靠完成。"],
            )
        return result.output

    tool = Tool[object](
        research_agent,
        takes_ctx=False,
        name=RESEARCH_AGENT_TOOL_NAME,
        sequential=False,
        description=(
            "Answer one bounded travel decision question discovered from a Candidate Plan. "
            "Use it for related reality gaps that can change that decision, not a general "
            "city fact survey. The child chooses its own research steps and returns "
            "compressed ResearchFindings. Multiple independent questions may be delegated."
        ),
    )
    return Capability[object](
        id=RESEARCH_AGENT_CAPABILITY_ID,
        description="Topic-level iterative research delegation for Main.",
        tools=(tool,),
    )


def build_research_workflow_capability(
    *,
    model: Model | KnownModelName | str | None,
) -> DynamicWorkflow:
    """Run independent research topics in one Harness workflow fan-out."""

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
