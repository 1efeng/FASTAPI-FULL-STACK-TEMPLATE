from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePosixPath

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool, tool

VIRTUAL_SKILLS_ROOT = PurePosixPath("/skills")


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
