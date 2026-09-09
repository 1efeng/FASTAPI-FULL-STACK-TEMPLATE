import ast
from pathlib import Path
from unittest.mock import patch

from pydantic_ai import Agent
from pydantic_ai.capabilities import AbstractCapability, Capability
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.agent.pydantic_executor import (
    _litellm_openai_base_url,
    _MainAgentRunDeps,
    _model_rpc_settings,
    get_chat_agent,
)
from app.core.config import settings


def test_chat_agent_uses_litellm_logical_model() -> None:
    agent = get_chat_agent()

    assert isinstance(agent, Agent)
    assert isinstance(agent.model, OpenAIResponsesModel)
    assert agent.model.model_name == settings.LLM_LOGICAL_MODEL


def test_chat_agent_enables_planning_and_web_tools_by_default() -> None:
    agent = get_chat_agent()
    leaves: list[AbstractCapability[_MainAgentRunDeps]] = []

    agent.root_capability.apply(leaves.append)

    capability_ids = {leaf.id for leaf in leaves}
    assert "travel-main-tools" in capability_ids
    assert "travel-plan-skill" in capability_ids
    assert "main-web-search" in capability_ids
    assert "travel-research-agent" not in capability_ids

    web_search_capability = next(
        leaf for leaf in leaves if leaf.id == "main-web-search"
    )
    assert isinstance(web_search_capability, Capability)
    assert "general news" in (web_search_capability.description or "")

    tools = {tool.name for leaf in leaves for tool in getattr(leaf, "tools", ())}
    assert "web_search" in tools
    assert "web_fetch" not in tools
    assert "research_agent" not in tools


def test_web_search_model_settings_do_not_inject_provider_native_tools() -> None:
    disabled = _model_rpc_settings(enable_web_search=False)
    enabled = _model_rpc_settings(enable_web_search=True)

    assert "openai_native_tools" not in disabled
    assert "openai_native_tools" not in enabled
    assert "openai_include_raw_annotations" not in disabled
    assert "openai_include_raw_annotations" not in enabled


def test_web_search_capability_resolves_per_run() -> None:
    observed_function_tools: list[list[str]] = []

    def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        assert messages
        observed_function_tools.append(
            [tool.name for tool in info.model_request_parameters.function_tools]
        )
        return ModelResponse(parts=[TextPart("ok")])

    model = FunctionModel(model_function)
    agent = get_chat_agent()

    assert (
        agent.run_sync(
            "disabled",
            model=model,
            deps=_MainAgentRunDeps(enable_web_search=False),
        ).output
        == "ok"
    )
    assert (
        agent.run_sync(
            "enabled",
            model=model,
            deps=_MainAgentRunDeps(enable_web_search=True),
        ).output
        == "ok"
    )

    assert "web_search" not in observed_function_tools[0]
    assert "web_search" in observed_function_tools[1]


def test_native_thinking_is_controlled_by_request_settings() -> None:
    disabled = _model_rpc_settings(enable_thinking=False)
    enabled = _model_rpc_settings(enable_thinking=True)

    assert "thinking" not in disabled
    assert disabled["extra_body"] == {"thinking": {"type": "disabled"}}
    assert enabled["extra_body"] == {"thinking": {"type": "enabled"}}

    model = get_chat_agent().model
    assert isinstance(model, OpenAIResponsesModel)
    prepared_settings, _ = model.prepare_request(
        disabled,
        ModelRequestParameters(),
    )
    assert prepared_settings is not None
    assert prepared_settings["extra_body"] == {"thinking": {"type": "disabled"}}


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
