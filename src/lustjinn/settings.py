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

    # The model. Every call goes to one OpenAI-compatible endpoint, OpenRouter by default; a
    # different provider that speaks the same shape is a change of URL and key.
    openrouter_api_key: SecretStr | None = None
    """The key. Optional here so the app starts without one; a model call without it fails
    before anything is sent."""

    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    model: str = "deepseek/deepseek-v4-flash"
    """The model that writes the replies. A story may name its own."""

    temperature: float = Field(default=1.0, ge=0, le=2)
    """Sampling temperature for a reply. Higher wanders further from the obvious."""

    max_tokens: int = Field(default=1024, ge=1, le=32768)
    """The ceiling on one reply, in tokens."""

    model_timeout_seconds: int = Field(default=180, ge=1, le=3600)
    """How long to wait for the model: to connect, and between one chunk and the next."""

    prefer_providers: list[str] = []
    """OpenRouter hosts to try first, by slug, as a JSON list. Others follow unless fallbacks
    are off."""

    ignore_providers: list[str] = []
    """OpenRouter hosts never to use, by slug, as a JSON list."""

    allow_provider_fallbacks: bool | None = None
    """Whether OpenRouter may use hosts outside `prefer_providers`. None leaves it to the router."""

    think_before_replying: bool = False
    """Whether a reply may spend tokens reasoning first. Off sends `reasoning: {enabled: false}`:
    without it the default model came back empty three times in five, every token spent
    thinking. Summaries and facts never send the field."""

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
