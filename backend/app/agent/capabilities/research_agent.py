"""High-level Main capability that delegates one bounded research topic."""

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
    VerificationItem,
    VerificationResult,
    build_research_agent,
)
from app.agent.bounded_research import run_bounded_research
from app.core.config import settings

RESEARCH_AGENT_TOOL_NAME = "research_agent"
RESEARCH_AGENT_CAPABILITY_ID = "travel-research-agent"
RESEARCH_WORKFLOW_CAPABILITY_ID = "travel-research-workflow"


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
        verification_items: list[VerificationItem],
        title: str | None = None,
        context: str | None = None,
        constraints: list[str] | None = None,
    ) -> ResearchFindings:
        """Investigate one bounded travel research topic and return evidence-backed findings."""
        request = ResearchRequest(
            objective=objective,
            title=title,
            verification_items=verification_items,
            context=context,
            constraints=constraints or [],
        )
        try:
            return await run_bounded_research(request, model=model)
        except (ModelAPIError, UnexpectedModelBehavior, UsageLimitExceeded):
            # One independent research topic must not abort sibling topics or the
            # whole Main plan when the child provider/output fails or exhausts its
            # own bounded research budget. Cancellation is BaseException and still
            # propagates to preserve Product runtime ownership.
            return ResearchFindings(
                topic=request.objective,
                verification_results=[
                    VerificationResult(
                        item_id=item.id,
                        summary="当前研究主题暂时无法可靠完成。",
                        status="unresolved",
                    )
                    for item in request.verification_items
                ],
                unresolved=["当前研究主题暂时无法可靠完成。"],
            )

    tool = Tool[object](
        research_agent,
        takes_ctx=False,
        name=RESEARCH_AGENT_TOOL_NAME,
        sequential=False,
        description=(
            "Use this tool for one bounded, evidence-heavy travel research topic "
            "whose raw evidence should stay out of Main context and whose completion "
            "criteria can be expressed as atomic verification_items. "
            "Do not use it for isolated facts or lightweight predetermined batches "
            "whose required tools/queries are already obvious to Main. "
            "verification_items are required."
        ),
    )
    return Capability[object](
        id=RESEARCH_AGENT_CAPABILITY_ID,
        description="Topic-level bounded context-isolated research delegation for Main.",
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
