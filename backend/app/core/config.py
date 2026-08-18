import secrets
import warnings
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    HttpUrl,
    PositiveFloat,
    PositiveInt,
    PostgresDsn,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file=ENV_FILE,
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    FRONTEND_HOST: str = "http://localhost:5173"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    APP_ENV: Literal["local", "test", "staging", "production"] = "local"
    APP_DEBUG: bool = False
    APP_TIMEZONE: str = "Asia/Shanghai"
    # Emergency wall-clock safety cap for one Product RequestRun. Normal long-running
    # research is bounded by per-RPC/tool timeouts and usage limits, not a short turn SLA.
    REQUEST_DEADLINE_SECONDS: PositiveFloat = 900.0
    # One model RPC remains independently bounded well below the Product safety cap.
    LITELLM_CLIENT_TIMEOUT_SECONDS: PositiveFloat = 240.0
    MAIN_MODEL_REQUEST_LIMIT: PositiveInt = 8
    MAIN_TOOL_CALL_LIMIT: PositiveInt = 16
    RESEARCH_AGENT_MODEL_REQUEST_LIMIT: PositiveInt = 8
    RESEARCH_AGENT_TOOL_CALL_LIMIT: PositiveInt = 18

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    PROJECT_NAME: str
    SENTRY_DSN: HttpUrl | None = None
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    DATABASE_URL: PostgresDsn | None = None
    OTEL_SERVICE_NAME: str = "travel-agent-api"
    OTLP_ENDPOINT: str | None = None
    AMAP_API_KEY: str | None = None
    WEB_SEARCH_API_KEY: str | None = None
    WEATHER_API_KEY: str | None = None
    QWEATHER_API_KEY: str | None = None
    QWEATHER_API_HOST: str = "https://devapi.qweather.com"
    FX_BASE_URL: str = "https://api.frankfurter.dev/v2"
    TRAVEL_CORE_ENABLED: bool = True

    # Shared runtime and AI infrastructure. These are configuration contracts;
    # feature modules connect to them when their roadmap milestone is enabled.
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_KEY_PREFIX: str = "travel_agent:"
    CHAT_IP_RATE_LIMIT_PER_MINUTE: PositiveInt = 60
    CHAT_USER_RATE_LIMIT_PER_MINUTE: PositiveInt = 20
    CHAT_DAILY_QUOTA: PositiveInt = 100
    CHAT_CONCURRENT_LIMIT: PositiveInt = 2
    CHAT_REDIS_FAILURE_POLICY: Literal["fail_open", "fail_closed"] = "fail_closed"
    LITELLM_BASE_URL: str = "http://localhost:4000"
    LITELLM_SERVICE_KEY: str = ""
    LLM_LOGICAL_MODEL: str = "travel-agent-llm"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        """异步驱动 URL,供应用与 asyncpg 使用"""
        if self.DATABASE_URL is not None:
            url = make_url(str(self.DATABASE_URL)).set(drivername="postgresql+asyncpg")
            return PostgresDsn(url.render_as_string(hide_password=False))
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI_SYNC(self) -> PostgresDsn:
        """同步驱动 URL,供 Alembic 迁移使用"""
        if self.DATABASE_URL is not None:
            url = make_url(str(self.DATABASE_URL)).set(drivername="postgresql+psycopg")
            return PostgresDsn(url.render_as_string(hide_password=False))
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.APP_ENV == "local" and self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_runtime_timeout_hierarchy(self) -> Self:
        if self.LITELLM_CLIENT_TIMEOUT_SECONDS >= self.REQUEST_DEADLINE_SECONDS:
            raise ValueError(
                "LITELLM_CLIENT_TIMEOUT_SECONDS must be less than "
                "REQUEST_DEADLINE_SECONDS"
            )
        return self

    @model_validator(mode="after")
    def _enforce_production_config(self) -> Self:
        if self.APP_ENV == "production" or self.ENVIRONMENT == "production":
            required = {
                "LITELLM_SERVICE_KEY": self.LITELLM_SERVICE_KEY,
            }
            missing = [name for name, value in required.items() if not value]
            if missing:
                raise ValueError(
                    "Missing required production configuration: " + ", ".join(missing)
                )
        return self

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self


settings = Settings()  # type: ignore
