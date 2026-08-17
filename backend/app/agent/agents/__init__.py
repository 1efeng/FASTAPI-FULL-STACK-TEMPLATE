"""Agent implementations used by the product-level composition root."""

from app.agent.agents.research_agent import (
    RESEARCH_AGENT_DESCRIPTION,
    RESEARCH_AGENT_INSTRUCTIONS,
    RESEARCH_AGENT_NAME,
    EvidenceClaim,
    EvidenceSource,
    ImageAsset,
    ResearchFindings,
    ResearchRequest,
    build_research_agent,
)

__all__ = [
    "RESEARCH_AGENT_DESCRIPTION",
    "RESEARCH_AGENT_INSTRUCTIONS",
    "RESEARCH_AGENT_NAME",
    "EvidenceClaim",
    "EvidenceSource",
    "ImageAsset",
    "ResearchFindings",
    "ResearchRequest",
    "build_research_agent",
]
