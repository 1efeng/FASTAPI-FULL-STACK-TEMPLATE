"""Agent middleware for the Aegra runtime.

These are application-level governance middleware, ported from the original
FastAPI chat agent. The framework (LangGraph ToolNode) still executes and
validates every tool; this module only adds skill loading and replay-safe
tool execution (idempotency ledger).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, tool

from travel_runtime.db import ToolInvocationStore

if TYPE_CHECKING:
    from langchain.agents.middleware.types import ToolCallRequest

VIRTUAL_SKILLS_ROOT = PurePosixPath("/skills")


def _jsonable(value: Any) -> Any:
    """Coerce tool output to JSON-serializable primitives for the ledger."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def _frontmatter_value(content: str, key: str) -> str | None:
    """Read one simple scalar value from a SKILL.md YAML frontmatter block."""
    match = re.search(r"^---\s*$.*?^---\s*$", content, re.MULTILINE | re.DOTALL)
    if not match:
        return None

    value = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", match.group(0), re.MULTILINE)
    if not value:
        return None

    return value.group(1).strip().strip('"\'')


class SkillsMiddleware(AgentMiddleware):
    """Expose skill metadata and loading instructions to the main Agent."""

    def __init__(self, skills_root: Path) -> None:
        self.skills_root = skills_root.resolve()
        self.skills_prompt = self._catalog()

    def _catalog(self) -> str:
        skills: list[str] = []
        if self.skills_root.is_dir():
            for skill_dir in sorted(self.skills_root.iterdir()):
                skill_file = skill_dir / "SKILL.md"
                if not skill_dir.is_dir() or not skill_file.is_file():
                    continue

                content = skill_file.read_text(encoding="utf-8")
                name = _frontmatter_value(content, "name") or skill_dir.name
                description = _frontmatter_value(content, "description") or ""
                path = VIRTUAL_SKILLS_ROOT / skill_dir.name / "SKILL.md"
                skills.append(f"- **{name}**: {description}\n  Read `{path}` for full instructions.")

        available = "\n".join(skills) or "(No skills available.)"
        return f"""## Skills System

You have access to specialized skills. The main Agent decides whether a skill
matches the user's current task.

Available skills:
{available}

When a skill applies, call `read_file` with its listed path before following
the skill. Do not load a skill for unrelated requests.
""".strip()

    def _request_with_catalog(self, request: ModelRequest) -> ModelRequest:
        current_system_message = request.system_message or SystemMessage(content="")
        if isinstance(current_system_message.content, str):
            system_message = SystemMessage(
                content=f"{current_system_message.content}\n\n{self.skills_prompt}"
            )
        else:
            system_message = SystemMessage(
                content=[
                    *current_system_message.content,
                    {"type": "text", "text": self.skills_prompt},
                ]
            )
        return request.override(system_message=system_message)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._request_with_catalog(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._request_with_catalog(request))


class FilesystemMiddleware(AgentMiddleware):
    """Expose a read-only virtual filesystem for skill files."""

    def __init__(self, skills_root: Path) -> None:
        root = skills_root.resolve()

        @tool("read_file")
        def read_file(file_path: str) -> str:
            """Read a skill or a supporting file under /skills/."""
            virtual_path = PurePosixPath(file_path)
            try:
                relative_path = virtual_path.relative_to(VIRTUAL_SKILLS_ROOT)
            except ValueError as exc:
                raise ValueError("file_path must be under /skills/") from exc

            target = (root / Path(*relative_path.parts)).resolve()
            if not target.is_relative_to(root):
                raise ValueError("file_path escapes the skills directory")
            if not target.is_file():
                raise FileNotFoundError(f"Skill file not found: {file_path}")

            return target.read_text(encoding="utf-8")

        self.tools: list[BaseTool] = [read_file]


class ToolIdempotencyMiddleware(AgentMiddleware):
    """Replay-safe tool execution via the ``tool_invocations`` ledger.

    LangGraph re-executes a pending tool call when a run is resumed from a
    checkpoint, with the same ``tool_call_id``. This middleware answers such
    replays from the ledger instead of running the tool again, so a tool whose
    side effect already succeeded is not repeated after a crash/restart. The
    cache is scoped by the Aegra thread id (set in ``config.configurable``).

    This is tool governance only; the framework (ToolNode) still executes and
    validates every tool.
    """

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Any]],
    ) -> ToolMessage | Any:
        tool_call_id = request.tool_call.get("id")
        tool_name = request.tool_call.get("name")
        config = getattr(request.runtime, "config", None) or {}
        thread_id = (config.get("configurable") or {}).get("thread_id")

        if not (tool_call_id and tool_name and thread_id):
            # No way to key the invocation: let the tool run normally.
            return await handler(request)

        cached = await ToolInvocationStore().get_succeeded_result(
            thread_id=thread_id,
            idempotency_key=tool_call_id,
        )
        if cached is not None:
            return ToolMessage(
                content=cached,
                tool_call_id=tool_call_id,
                name=tool_name,
            )

        response = await handler(request)
        if isinstance(response, ToolMessage):
            status = "SUCCEEDED" if response.status != "error" else "FAILED"
            await ToolInvocationStore().record(
                thread_id=thread_id,
                tool_name=tool_name,
                idempotency_key=tool_call_id,
                status=status,
                result=_jsonable(response.content),
            )
        return response
