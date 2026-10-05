from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from lustjinn.main import app
from lustjinn.settings import Settings, get_settings

VALID = {
    "LUSTJINN_DATABASE_URL": "postgresql+asyncpg://someone:secret@localhost:5440/lustjinn",
    "LUSTJINN_USERNAME": "reader",
    "LUSTJINN_PASSWORD": "a password",
    "LUSTJINN_TOKEN_SECRET": "x" * 32,
}


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    """A clean slate: valid variables, and a working directory with no `.env` in it."""
    monkeypatch.chdir(tmp_path)
    for name, value in VALID.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


@pytest.fixture
def fresh_settings() -> Iterator[None]:
    """`get_settings` remembers its answer; forget it around a test that changes the environment."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def read() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]


def test_settings_are_read_from_the_environment(environment: pytest.MonkeyPatch) -> None:
    settings = read()

    assert settings.username == "reader"
    assert settings.password.get_secret_value() == "a password"
    assert settings.token_days == 30
    assert settings.cors_origins == []


def test_a_secret_does_not_print_itself(environment: pytest.MonkeyPatch) -> None:
    assert "a password" not in repr(read())


def test_a_list_is_read_as_json(environment: pytest.MonkeyPatch) -> None:
    environment.setenv("LUSTJINN_CORS_ORIGINS", '["http://localhost:5173"]')

    assert read().cors_origins == ["http://localhost:5173"]


@pytest.mark.parametrize("missing", list(VALID))
def test_a_missing_required_variable_is_refused(
    environment: pytest.MonkeyPatch, missing: str
) -> None:
    environment.delenv(missing)

    with pytest.raises(ValidationError):
        read()


def test_a_short_token_secret_is_refused(environment: pytest.MonkeyPatch) -> None:
    environment.setenv("LUSTJINN_TOKEN_SECRET", "too short")

    with pytest.raises(ValidationError):
        read()


def test_a_database_url_for_another_driver_is_refused(environment: pytest.MonkeyPatch) -> None:
    environment.setenv("LUSTJINN_DATABASE_URL", "postgresql://someone:secret@localhost/lustjinn")

    with pytest.raises(ValidationError, match="asyncpg"):
        read()


@pytest.mark.usefixtures("fresh_settings")
def test_the_app_refuses_to_start_without_its_settings(environment: pytest.MonkeyPatch) -> None:
    environment.delenv("LUSTJINN_PASSWORD")

    # Entering the client runs the app's start-up, as uvicorn would.
    with pytest.raises(ValidationError), TestClient(app):
        pass


@pytest.mark.usefixtures("fresh_settings", "environment")
def test_the_app_starts_with_its_settings() -> None:
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
