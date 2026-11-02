"""
https://fastapi.tiangolo.com/advanced/settings/
https://docs.pydantic.dev/latest/concepts/pydantic_settings
"""

import os
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import HttpUrl, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from shared.infra.di import Depends


def _determine_dotenv_file() -> None | str | list[str]:
    """Determine the .env file to use based on the APP_ENV variable."""
    env = os.getenv("APP_ENV", "development")
    if env == "development":
        return ".env"
    if env == "test":
        return [".env", ".env.test"]

    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Even when using a dotenv file, pydantic will still read environment
        # variables as well as the dotenv file. *Environment variables will always
        # take priority over values loaded from a dotenv file*.
        env_file=_determine_dotenv_file(),
        env_file_encoding="utf-8",
        extra="allow",  # allow fields in .env that are not defined here
    )

    # Application
    APP_ENV: Literal["development", "test", "staging", "production"] = "development"
    APP_DEBUG: bool = False
    APP_VERSION: str = "0.0.0"
    APP_DEBUG: bool = False
    APP_SECRET: SecretStr
    PERSONAL_DATA_ENCRYPTION_KEY: SecretStr
    LOGGING_LEVEL: str = "INFO"
    PUBLIC_API_URL: str
    PUBLIC_FRONTEND_URL: str
    CORS_ALLOWED_ORIGINS: str
    CORS_ALLOW_ORIGIN_REGEX: str | None = None

    RESEND_API_KEY: SecretStr | None = None
    NOTIFICATIONS_FROM_EMAIL: str = "Eventhub <no-reply@example.com>"

    DATABASE_URL: PostgresDsn

    SENTRY_DSN: HttpUrl | None = None

    REDIS_DSN: str = "redis://redis:6379/0"
    RABBITMQ_DSN: str = "amqp://eventhub:eventhub@rabbitmq:5672/%2F"
    QUEUE_RESULT_BACKEND_DSN: str = "redis://redis:6379/0"

    S3_ENDPOINT_URL: str | None
    S3_PUBLIC_BASE_URL: str
    S3_REGION_NAME: str
    S3_ACCESS_KEY: str
    S3_SECRET_KEY: str
    S3_BUCKET_EVENT_IMAGES: str = "event-images"

    def is_test(self) -> bool:
        """Whether the application is running in test environment."""
        return self.APP_ENV == "test"

    def is_dev(self) -> bool:
        """Whether the application is running in dev environment."""
        return self.APP_ENV == "development"

    def is_dev_like(self) -> bool:
        """Whether the application is running in a dev-like environment."""
        return self.APP_ENV in ("development", "test")

    def is_dev_or_staging(self) -> bool:
        return self.APP_ENV in ("development", "staging")

    def is_prod(self) -> bool:
        """Whether the application is running in a production environment."""
        return self.APP_ENV == "production"

    def is_prod_like(self) -> bool:
        """Whether the application is running in a prod-like environment."""
        return self.APP_ENV in ("production", "staging")


# Values will be read from .env or environment variables
settings = Settings()


@lru_cache
def get_settings() -> Settings:
    return Settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]
