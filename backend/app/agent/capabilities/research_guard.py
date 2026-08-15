"""Host-side invariants for Deep Research workflow invocation."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import SkipToolExecution
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import RunContext, ToolDefinition


@dataclass
class SingleWorkflowCallGate(AbstractCapability[object]):
    """Allow at most one ``run_workflow`` execution per Main Agent run.

    Harness ``max_agent_calls`` limits child runs, not workflow invocations. This
    capability owns the separate Product invariant: after the first Deep Research
    workflow starts, every later attempt is host-rejected without executing Harness.
    """

    tool_name: str = "run_workflow"
    _used: bool = field(default=False, init=False, repr=False)

    @classmethod
    def get_serialization_name(cls) -> str | None:
        return None

    async def for_run(self, ctx: RunContext[object]) -> SingleWorkflowCallGate:
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
        if self._used:
            raise SkipToolExecution(
                {
                    "error": "DEEP_RESEARCH_ALREADY_USED",
                    "message": (
                        "This request already used its single Deep Research workflow. "
                        "Conclude from existing findings and mark remaining facts unresolved."
                    ),
                }
            )
        # Suspension-free reservation: if a future core version ever permits two
        # same-name sequential calls in one model step, the second still loses.
        self._used = True
        return args
