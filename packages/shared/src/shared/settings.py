"""
https://fastapi.tiangolo.com/advanced/settings/
https://docs.pydantic.dev/latest/concepts/pydantic_settings
"""

import os
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import SecretStr
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
    LOGGING_LEVEL: str = "INFO"
    PUBLIC_URL: str

    DATABASE_URL: str

    SENTRY_DSN: str
    CORS_ALLOWED_ORIGINS: str
    CORS_ALLOW_ORIGIN_REGEX: str | None = None

    RABBITMQ_DSN: str = "amqp://eventhub:eventhub@rabbitmq:5672/%2F"
    QUEUE_RESULT_BACKEND_DSN: str = "redis://redis:6379/0"

    def is_test(self) -> bool:
        """Whether the application is running in test environment."""
        return self.APP_ENV == "test"

    def is_dev(self) -> bool:
        """Whether the application is running in dev environment."""
        return self.APP_ENV == "development"

    def is_dev_like(self) -> bool:
        """Whether the application is running in a dev-like environment."""
        return self.APP_ENV in ("development", "test")

    def is_prod(self) -> bool:
        """Whether the application is running in a production environment."""
        return self.APP_ENV == "production"

    def is_prod_like(self) -> bool:
        """Whether the application is running in a prod-like environment."""
        return self.APP_ENV in ("production", "staging")


# Values will be read from .env or environment variables
settings = Settings()  # type: ignore


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore


SettingsDep = Annotated[Settings, Depends(get_settings)]
