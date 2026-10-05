"""Typed configuration, read from the environment and a local `.env` file."""

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ASYNC_POSTGRES = "postgresql+asyncpg://"


class Settings(BaseSettings):
    """Every value the app needs from outside. A missing required one stops the app at start-up.

    Each field is read from the variable `LUSTJINN_<FIELD>`: `LUSTJINN_DATABASE_URL`, and so on.
    Real environment variables win over the `.env` file.
    """

    model_config = SettingsConfigDict(env_prefix="LUSTJINN_", env_file=".env", extra="ignore")

    database_url: str
    """Where Postgres is, as SQLAlchemy reads it: `postgresql+asyncpg://user:password@host:port/db`."""

    username: str
    """The one user's sign-in name."""

    password: SecretStr
    """The one user's password. `SecretStr` keeps it out of logs and error messages."""

    token_secret: SecretStr = Field(min_length=32)
    """Signs the bearer tokens. Changing it signs every device out."""

    token_days: int = Field(default=30, ge=1, le=365)
    """How long a bearer token lasts before the client must sign in again."""

    cors_origins: list[str] = []
    """Origins allowed to call the API from a browser, as a JSON list. Empty allows none."""

    @field_validator("database_url")
    @classmethod
    def _must_use_the_async_driver(cls, value: str) -> str:
        if not value.startswith(ASYNC_POSTGRES):
            raise ValueError(
                f"must start with {ASYNC_POSTGRES} — the app talks to Postgres through asyncpg"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    """The settings, read once. FastAPI injects this; tests override it."""
    return Settings()  # pyright: ignore[reportCallIssue] — the fields come from the environment
