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

    context_budget: int = Field(default=32_000, ge=1000, le=900_000)
    """The most tokens a prompt may hold, counted with the model's own vocabulary — far below
    the model's window on purpose: attention thins out, and every token is paid for on every
    turn. When it binds, the oldest history gives way; the newest turn is always kept."""

    recall_percent: int = Field(default=10, ge=0, le=50)
    """The share of the budget recalled memories may take, whatever their count: four long
    recalled turns once filled a 60,000-token prompt."""

    prefer_providers: list[str] = []
    """OpenRouter hosts to try first, by slug, as a JSON list. Others follow unless fallbacks
    are off."""

    ignore_providers: list[str] = []
    """OpenRouter hosts never to use, by slug, as a JSON list."""

    allow_provider_fallbacks: bool | None = None
    """Whether OpenRouter may use hosts outside `prefer_providers`. None leaves it to the router."""

    background_model: str | None = None
    """The model for summaries and facts; None means the default model. Criterion one is the
    same as for replies — it must not refuse — since a refusing summariser is a character that
    forgets."""

    embedding_model: str | None = "openai/text-embedding-3-small"
    """The model that embeds summarised turns for retrieval; None switches retrieval off.
    DeepSeek offers no embeddings, so this stays on OpenRouter whatever writes the replies."""

    recall_count: int = Field(default=4, ge=0, le=20)
    """How many recalled turns a prompt may carry at most. A ceiling, not a target — and the
    share of the budget (`recall_percent`) binds first."""

    recall_threshold: float = Field(default=0.35, ge=0, le=1)
    """The least cosine similarity a turn needs to be recalled. Below it, nothing is."""

    model_choices: list[str] = [
        "cognitivecomputations/dolphin-mistral-24b-venice-edition",
        "thedrummer/cydonia-24b-v4.1",
        "anthracite-org/magnum-v4-72b",
        "thedrummer/unslopnemo-12b",
        "deepseek/deepseek-v4-pro",
        "z-ai/glm-4.6",
    ]
    """The models a story may be offered, as a JSON list. The shipped six were each tried on
    2026-10-01 with one scene at four temperatures: four roleplay finetunes chosen to be more
    willing than the default, and two larger general models that wrote the scene once their
    reasoning was off. Labelled with the provider's list prices, to compare by only."""

    model_windows: dict[str, int] = {}
    """The context a model can really use, by id, where it is smaller than the provider lists —
    as a JSON object. A correction here is believed over the list and over the shipped ones."""

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
