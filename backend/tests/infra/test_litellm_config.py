from pathlib import Path

import pytest
import yaml

_CONFIG_PATH = Path(__file__).parents[3] / "infra" / "litellm" / "config.yaml"


def _config() -> dict[str, object]:
    with _CONFIG_PATH.open(encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def test_litellm_production_config_matches_retry_contract() -> None:
    config = _config()
    models = {
        model["model_name"]: model["litellm_params"]
        for model in config["model_list"]
    }

    assert set(models) == {"travel-agent-llm", "travel-doubao"}
    assert models["travel-agent-llm"]["model"] == "openai/deepseek-v4-flash"
    assert models["travel-agent-llm"]["mode"] == "responses"
    assert models["travel-agent-llm"]["api_base"] == "os.environ/DOUBAO_PLAN_BASE_URL"
    assert models["travel-agent-llm"]["api_key"] == "os.environ/DOUBAO_PLAN_API_KEY"
    assert all(
        params["timeout"] == 120 and params["stream_timeout"] == 120
        for params in models.values()
    )

    primary_model_info = next(
        model["model_info"]
        for model in config["model_list"]
        if model["model_name"] == "travel-agent-llm"
    )
    assert primary_model_info["mode"] == "responses"

    router = config["router_settings"]
    assert router["num_retries"] == 0
    assert router["max_fallbacks"] == 1
    assert router["fallbacks"] == [{"travel-agent-llm": ["travel-doubao"]}]
    assert router["retry_policy"] == {
        "BadRequestErrorRetries": 0,
        "AuthenticationErrorRetries": 0,
        "TimeoutErrorRetries": 0,
        "RateLimitErrorRetries": 1,
        "ContentPolicyViolationErrorRetries": 0,
        "InternalServerErrorRetries": 1,
    }

    assert config["litellm_settings"]["request_timeout"] == 120


@pytest.mark.parametrize(
    ("retry_key", "expected_retries"),
    [
        ("BadRequestErrorRetries", 0),
        ("AuthenticationErrorRetries", 0),
        ("ContentPolicyViolationErrorRetries", 0),
        ("TimeoutErrorRetries", 0),
        ("RateLimitErrorRetries", 1),
        ("InternalServerErrorRetries", 1),
    ],
)
def test_litellm_retry_policy_is_explicit(
    retry_key: str,
    expected_retries: int,
) -> None:
    retry_policy = _config()["router_settings"]["retry_policy"]

    assert retry_policy[retry_key] == expected_retries
