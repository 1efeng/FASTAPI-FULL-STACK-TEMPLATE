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
