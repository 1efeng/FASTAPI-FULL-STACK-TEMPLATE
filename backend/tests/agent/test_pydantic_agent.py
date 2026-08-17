import ast
from pathlib import Path
from unittest.mock import patch

from pydantic_ai import Agent
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.agent.pydantic_executor import _litellm_openai_base_url, get_chat_agent
from app.core.config import settings


def test_chat_agent_uses_litellm_logical_model() -> None:
    agent = get_chat_agent()

    assert isinstance(agent, Agent)
    assert isinstance(agent.model, OpenAIResponsesModel)
    assert agent.model.model_name == settings.LLM_LOGICAL_MODEL


def test_chat_agent_enables_planning_and_research_agent_by_default() -> None:
    agent = get_chat_agent()
    leaves: list[AbstractCapability[object]] = []

    agent.root_capability.apply(leaves.append)

    capability_ids = {leaf.id for leaf in leaves}
    assert "travel-budget" in capability_ids
    assert "travel-main-tools" in capability_ids
    assert "travel-planning" in capability_ids
    assert "travel-research-agent" in capability_ids
    assert "deep-research" not in capability_ids


def test_runtime_clock_is_resolved_fresh_for_each_agent_run() -> None:
    observed_instructions: list[str] = []

    def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        assert messages
        observed_instructions.append(info.instructions or "")
        return ModelResponse(parts=[TextPart("ok")])

    agent = get_chat_agent()
    model = FunctionModel(model_function)
    with patch(
        "app.agent.pydantic_executor.runtime_clock_context",
        side_effect=("clock-run-one", "clock-run-two"),
    ) as clock:
        assert agent.run_sync("first", model=model).output == "ok"
        assert agent.run_sync("second", model=model).output == "ok"

    assert clock.call_count == 2
    assert "clock-run-one" in observed_instructions[0]
    assert "clock-run-two" not in observed_instructions[0]
    assert "clock-run-two" in observed_instructions[1]
    assert "clock-run-one" not in observed_instructions[1]


def test_chat_agent_provider_points_at_litellm_gateway() -> None:
    agent = get_chat_agent()
    model = agent.model

    assert isinstance(model, OpenAIResponsesModel)
    assert isinstance(model.provider, OpenAIProvider)
    assert (model.provider.base_url or "").rstrip("/").endswith("/v1")


def test_litellm_openai_base_url_normalizes_to_v1() -> None:
    assert _litellm_openai_base_url().rstrip("/").endswith("/v1")


def test_product_modules_do_not_import_agent_framework_types() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    framework_imports: list[str] = []

    executor_port = backend_dir / "app" / "agent" / "executor.py"
    usage_port = backend_dir / "app" / "agent" / "usage.py"
    product_files = [
        executor_port,
        usage_port,
        *(backend_dir / "app" / "modules").rglob("*.py"),
    ]
    for path in product_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported_modules = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        imported_modules.extend(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        if any(
            module == "pydantic_ai"
            or module.startswith("pydantic_ai.")
            or module == "pydantic_ai_harness"
            or module.startswith("pydantic_ai_harness.")
            or (
                path != executor_port
                and (
                    module == "app.agent.pydantic_executor"
                    or module.startswith("app.agent.pydantic_executor.")
                )
            )
            for module in imported_modules
        ):
            framework_imports.append(str(path.relative_to(backend_dir)))

    assert framework_imports == []
