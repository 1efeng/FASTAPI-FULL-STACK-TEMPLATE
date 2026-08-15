import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "PROJECT_NAME": "Travel Agent Test",
        "POSTGRES_SERVER": "localhost",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "safe-postgres-password",
        "POSTGRES_DB": "app",
        "FIRST_SUPERUSER": "admin@example.com",
        "FIRST_SUPERUSER_PASSWORD": "safe-superuser-password",
        "SECRET_KEY": "safe-secret-key",
        "LITELLM_SERVICE_KEY": "sk-test",
    }
    values.update(overrides)
    return Settings.model_validate(values)


@pytest.mark.parametrize(
    "secret_name",
    ["SECRET_KEY", "POSTGRES_PASSWORD", "FIRST_SUPERUSER_PASSWORD"],
)
def test_production_rejects_default_secrets(secret_name: str) -> None:
    with pytest.raises(ValidationError, match=secret_name):
        _settings(
            APP_ENV="production",
            ENVIRONMENT="local",
            **{secret_name: "changethis"},
        )


def test_database_url_is_the_database_source_of_truth() -> None:
    configured = _settings(
        DATABASE_URL="postgresql://app_user:secret@database.internal:5433/travel"
    )

    assert str(configured.SQLALCHEMY_DATABASE_URI) == (
        "postgresql+asyncpg://app_user:secret@database.internal:5433/travel"
    )
    assert str(configured.SQLALCHEMY_DATABASE_URI_SYNC) == (
        "postgresql+psycopg://app_user:secret@database.internal:5433/travel"
    )


def test_runtime_budget_defaults_match_main_and_worker_contract() -> None:
    configured = _settings()

    assert configured.REQUEST_DEADLINE_SECONDS == 300.0
    assert configured.LITELLM_CLIENT_TIMEOUT_SECONDS == 150.0
    assert configured.MAIN_MODEL_REQUEST_LIMIT == 8
    assert configured.MAIN_TOOL_CALL_LIMIT == 6
    assert configured.RESEARCH_WORKER_MODEL_REQUEST_LIMIT == 8
    assert configured.RESEARCH_WORKER_TOOL_CALL_LIMIT == 18
    assert not hasattr(configured, "TRAVEL_RESEARCHER_TIMEOUT_SECONDS")
    assert not hasattr(configured, "TRAVEL_RESEARCHER_MODEL_REQUEST_LIMIT")
    assert not hasattr(configured, "TRAVEL_RESEARCHER_TOOL_CALL_LIMIT")
    assert not hasattr(configured, "TAVILY_API_KEY")


def test_runtime_budget_hierarchy_is_strict() -> None:
    configured = _settings()

    assert (
        0
        < configured.LITELLM_CLIENT_TIMEOUT_SECONDS
        < configured.REQUEST_DEADLINE_SECONDS
    )


def test_legacy_agent_timeout_switch_is_ignored() -> None:
    configured = _settings(AGENT_EXECUTION_TIMEOUT_ENABLED=False)

    assert not hasattr(configured, "AGENT_EXECUTION_TIMEOUT_ENABLED")


def test_runtime_budget_respects_env_override() -> None:
    configured = _settings(
        REQUEST_DEADLINE_SECONDS=500.0,
        LITELLM_CLIENT_TIMEOUT_SECONDS=300.0,
        RESEARCH_WORKER_MODEL_REQUEST_LIMIT=7,
        RESEARCH_WORKER_TOOL_CALL_LIMIT=15,
    )

    assert configured.REQUEST_DEADLINE_SECONDS == 500.0
    assert configured.LITELLM_CLIENT_TIMEOUT_SECONDS == 300.0
    assert configured.RESEARCH_WORKER_MODEL_REQUEST_LIMIT == 7
    assert configured.RESEARCH_WORKER_TOOL_CALL_LIMIT == 15


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("LITELLM_CLIENT_TIMEOUT_SECONDS", 0.0),
        ("RESEARCH_WORKER_MODEL_REQUEST_LIMIT", 0),
        ("RESEARCH_WORKER_TOOL_CALL_LIMIT", 0),
    ],
)
def test_runtime_budget_rejects_non_positive(field: str, value: float | int) -> None:
    with pytest.raises(ValidationError, match=field):
        _settings(**{field: value})
