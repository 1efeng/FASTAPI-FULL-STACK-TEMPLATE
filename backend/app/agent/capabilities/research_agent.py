"""High-level Main capability that delegates one bounded research objective."""

from __future__ import annotations

from pydantic_ai import Tool, UsageLimits
from pydantic_ai.capabilities import Capability
from pydantic_ai.models import KnownModelName, Model

from app.agent.agents.research_agent import (
    ResearchFindings,
    ResearchRequest,
    build_research_agent,
)
from app.core.config import settings

RESEARCH_AGENT_TOOL_NAME = "research_agent"
RESEARCH_AGENT_CAPABILITY_ID = "travel-research-agent"


def _format_research_request(request: ResearchRequest) -> str:
    """Serialize only the explicit handoff contract into the child context."""
    return request.model_dump_json(exclude_none=True)


def build_research_agent_capability(
    *,
    model: Model | KnownModelName | str | None,
) -> Capability[object]:
    """Expose ``research_agent`` to Main as one compressed child-agent tool.

    The child executes inline in the current Main tool await chain, so Product
    cancellation naturally propagates. Only ``ResearchFindings`` is returned to
    Main; the child model/tool trajectory remains inside the child run.
    """
    research = build_research_agent(model=model)

    async def research_agent(
        objective: str,
        context: str | None = None,
        constraints: list[str] | None = None,
    ) -> ResearchFindings:
        """Investigate one complex travel research objective and return evidence-backed findings."""
        request = ResearchRequest(
            objective=objective,
            context=context,
            constraints=constraints or [],
        )
        result = await research.run(
            _format_research_request(request),
            usage_limits=UsageLimits(
                request_limit=settings.RESEARCH_AGENT_MODEL_REQUEST_LIMIT,
                tool_calls_limit=settings.RESEARCH_AGENT_TOOL_CALL_LIMIT,
            ),
        )
        return result.output

    tool = Tool[object](
        research_agent,
        takes_ctx=False,
        name=RESEARCH_AGENT_TOOL_NAME,
        description=(
            "Use only for a complex, multi-step, multi-source travel research objective "
            "that needs iterative investigation. Returns compressed ResearchFindings."
        ),
    )
    return Capability[object](
        id=RESEARCH_AGENT_CAPABILITY_ID,
        description="Bounded iterative research delegation for Main.",
        tools=(tool,),
    )
