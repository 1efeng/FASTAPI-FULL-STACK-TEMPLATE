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


def test_runtime_budget_defaults_match_contract() -> None:
    """A1 contract: App->LiteLLM 150 < Researcher 240 < Product 300."""
    configured = _settings()

    assert configured.REQUEST_DEADLINE_SECONDS == 300.0
    assert configured.TRAVEL_RESEARCHER_TIMEOUT_SECONDS == 240.0
    assert configured.LITELLM_CLIENT_TIMEOUT_SECONDS == 150.0


def test_runtime_budget_hierarchy_is_strict() -> None:
    configured = _settings()

    assert (
        0
        < configured.LITELLM_CLIENT_TIMEOUT_SECONDS
        < configured.TRAVEL_RESEARCHER_TIMEOUT_SECONDS
        < configured.REQUEST_DEADLINE_SECONDS
    )


def test_runtime_budget_respects_env_override() -> None:
    """pydantic-settings env override path still parses the new fields."""
    configured = _settings(
        REQUEST_DEADLINE_SECONDS=500.0,
        TRAVEL_RESEARCHER_TIMEOUT_SECONDS=400.0,
        LITELLM_CLIENT_TIMEOUT_SECONDS=300.0,
    )

    assert configured.REQUEST_DEADLINE_SECONDS == 500.0
    assert configured.TRAVEL_RESEARCHER_TIMEOUT_SECONDS == 400.0
    assert configured.LITELLM_CLIENT_TIMEOUT_SECONDS == 300.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("TRAVEL_RESEARCHER_TIMEOUT_SECONDS", -1.0),
        ("LITELLM_CLIENT_TIMEOUT_SECONDS", 0.0),
    ],
)
def test_runtime_budget_rejects_non_positive(field: str, value: float) -> None:
    with pytest.raises(ValidationError, match=field):
        _settings(**{field: value})
