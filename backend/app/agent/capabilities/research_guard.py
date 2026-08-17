"""Host-side invariant for bounded Research Agent delegation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import SkipToolExecution
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import RunContext, ToolDefinition

from app.agent.debug_logging import debug_runtime_log


@dataclass
class ResearchAgentCallGate(AbstractCapability[object]):
    """Allow at most one ``research_agent`` execution per Main Agent run."""

    tool_name: str = "research_agent"
    _used: bool = field(default=False, init=False, repr=False)

    @classmethod
    def get_serialization_name(cls) -> str | None:
        return None

    async def for_run(self, ctx: RunContext[object]) -> ResearchAgentCallGate:
        del ctx
        clone = replace(self)
        clone._used = False
        return clone

    async def before_tool_execute(
        self,
        ctx: RunContext[object],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        del ctx, tool_def
        if call.tool_name != self.tool_name:
            return args

        debug_runtime_log(
            hypothesis_id="H1",
            location="research_guard.py:before_tool_execute",
            message="main requested research agent",
            data={"research_used_before": self._used},
        )
        if self._used:
            raise SkipToolExecution(
                {
                    "error": "RESEARCH_AGENT_ALREADY_USED",
                    "message": (
                        "This request already used its single complex research run. "
                        "Conclude from existing findings and mark remaining facts unresolved."
                    ),
                }
            )

        self._used = True
        return args
