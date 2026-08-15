"""Hard wall-clock bound for one external tool execution.

Every external IO tool must finish within a bounded window so a hung provider
can never consume the Product deadline (300s) or the Researcher budget (240s)
from inside a single tool call. The tool layer owns this boundary — it is the
tightest time owner, kept well below the model RPC timeout (150s) so a stuck
provider cannot eat a model turn.

This is deliberately a code constant, not a config key: it is a runtime safety
limit owned by the tool layer, and the architecture contract forbids duplicate
timeout owners.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable

# One external tool call must complete within this window. Kept equal to the
# web_fetch bound (30s) and strictly below LITELLM_CLIENT_TIMEOUT_SECONDS (150s):
#   0 < TOOL_EXECUTION_TIMEOUT_SECONDS < 150 < 240 < 300
TOOL_EXECUTION_TIMEOUT_SECONDS: float = 30.0


async def bound_tool_execution[T](coro: Awaitable[T]) -> T:
    """Run one external tool call under the hard execution bound.

    A timeout cancels the underlying work and raises ``TimeoutError``, which the
    tool's existing ``except Exception`` path converts into the standard degraded
    text result — the model never sees the hang.
    """
    return await asyncio.wait_for(coro, timeout=TOOL_EXECUTION_TIMEOUT_SECONDS)
