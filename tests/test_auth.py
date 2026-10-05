"""Sign-in, the bearer token, and the guard in front of everything else."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from pydantic import SecretStr

from lustjinn.auth import issue_token, sign
from lustjinn.main import app, create_app
from lustjinn.settings import Settings

OPEN = {"/health", "/auth/sign-in"}
"""The only routes that answer without a token."""


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def sign_in(client: httpx2.AsyncClient, username: str, password: str) -> httpx2.Response:
    return await client.post("/auth/sign-in", json={"username": username, "password": password})


async def test_signing_in_returns_a_token_that_opens_the_api(
    anonymous: httpx2.AsyncClient, settings: Settings
) -> None:
    response = await sign_in(anonymous, "reader", "correct horse battery staple")

    assert response.status_code == 200
    token = response.json()
    assert token["token_type"] == "bearer"
    assert (
        await anonymous.get("/stories", headers=bearer(token["access_token"]))
    ).status_code == 200


async def test_the_token_lasts_as_long_as_the_settings_say(
    anonymous: httpx2.AsyncClient, settings: Settings
) -> None:
    token = (await sign_in(anonymous, "reader", "correct horse battery staple")).json()

    lasts = datetime.fromisoformat(token["expires_at"]) - datetime.now(UTC)

    assert settings.token_days == 30
    assert timedelta(days=30) - timedelta(minutes=1) < lasts <= timedelta(days=30)


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("reader", "wrong"),
        ("someone else", "correct horse battery staple"),
        ("", ""),
        ("READER", "correct horse battery staple"),
    ],
)
async def test_wrong_credentials_are_refused_without_saying_which_was_wrong(
    anonymous: httpx2.AsyncClient, username: str, password: str
) -> None:
    response = await sign_in(anonymous, username, password)

    assert response.status_code == 401
    assert response.json()["detail"] == "Wrong username or password."
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_the_password_is_not_echoed_back_when_the_request_is_malformed(
    anonymous: httpx2.AsyncClient,
) -> None:
    response = await anonymous.post("/auth/sign-in", json={"password": "hunter2-secret"})

    assert response.status_code == 422
    assert "hunter2-secret" not in response.text


async def test_without_a_token_the_api_says_to_sign_in(anonymous: httpx2.AsyncClient) -> None:
    response = await anonymous.get("/stories")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert "Sign in first" in response.json()["detail"]


async def test_every_route_but_health_and_sign_in_needs_a_token(
    anonymous: httpx2.AsyncClient,
) -> None:
    """Walks the app's own description of itself, so a route added later is covered for free."""
    paths: dict[str, dict[str, object]] = app.openapi()["paths"]
    guarded = {path: methods for path, methods in paths.items() if path not in OPEN}
    assert len(guarded) >= 2  # /stories and /stories/{story_id}, at least

    for path, methods in guarded.items():
        url = path.replace("{story_id}", str(uuid.uuid7()))
        for method in methods:
            response = await anonymous.request(method.upper(), url, json={})
            assert response.status_code == 401, f"{method} {path} answered without a token"


async def test_health_needs_no_token(anonymous: httpx2.AsyncClient) -> None:
    assert (await anonymous.get("/health")).status_code == 200


async def test_a_token_that_is_not_a_token_is_refused(anonymous: httpx2.AsyncClient) -> None:
    response = await anonymous.get("/stories", headers=bearer("not.a.token"))

    assert response.status_code == 401
    assert "not valid" in response.json()["detail"]


async def test_a_token_signed_with_another_secret_is_refused(
    anonymous: httpx2.AsyncClient, settings: Settings
) -> None:
    forged = settings.model_copy(update={"token_secret": SecretStr("another-secret-" + "x" * 32)})

    response = await anonymous.get("/stories", headers=bearer(issue_token(forged).access_token))

    assert response.status_code == 401


async def test_an_expired_token_is_refused_and_says_so(
    anonymous: httpx2.AsyncClient, settings: Settings
) -> None:
    long_ago = datetime.now(UTC) - timedelta(days=settings.token_days + 1)

    response = await anonymous.get(
        "/stories", headers=bearer(issue_token(settings, now=long_ago).access_token)
    )

    assert response.status_code == 401
    assert "expired" in response.json()["detail"]


async def test_a_token_for_someone_else_is_refused(
    anonymous: httpx2.AsyncClient, settings: Settings
) -> None:
    """Correctly signed, not expired — but changing the username must sign the old one out."""
    other = settings.model_copy(update={"username": "someone else"})

    response = await anonymous.get("/stories", headers=bearer(issue_token(other).access_token))

    assert response.status_code == 401


async def test_a_token_with_no_expiry_is_refused(
    anonymous: httpx2.AsyncClient, settings: Settings
) -> None:
    forever = sign({"sub": settings.username}, settings.token_secret.get_secret_value())

    assert (await anonymous.get("/stories", headers=bearer(forever))).status_code == 401


async def test_a_token_claiming_no_signature_is_refused(
    anonymous: httpx2.AsyncClient, settings: Settings
) -> None:
    """The classic forgery: a token that says "alg: none" and carries no signature at all."""
    unsigned = sign(
        {"sub": settings.username, "exp": datetime.now(UTC) + timedelta(days=1)},
        secret="",
        algorithm="none",
    )

    assert (await anonymous.get("/stories", headers=bearer(unsigned))).status_code == 401


async def test_another_scheme_is_not_a_bearer_token(anonymous: httpx2.AsyncClient) -> None:
    response = await anonymous.get("/stories", headers={"Authorization": "Basic cmVhZGVyOng="})

    assert response.status_code == 401


async def test_every_response_says_it_is_private(anonymous: httpx2.AsyncClient) -> None:
    for response in (await anonymous.get("/health"), await anonymous.get("/stories")):
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert response.headers["X-Robots-Tag"] == "noindex, nofollow"
        assert response.headers["X-Content-Type-Options"] == "nosniff"


async def test_no_browser_origin_is_allowed_unless_the_settings_name_it(
    anonymous: httpx2.AsyncClient,
) -> None:
    response = await anonymous.get("/health", headers={"Origin": "https://somewhere.example"})

    assert "Access-Control-Allow-Origin" not in response.headers


async def test_an_origin_the_settings_name_is_allowed(settings: Settings) -> None:
    allowing = settings.model_copy(update={"cors_origins": ["https://lustjinn.example"]})
    transport = httpx2.ASGITransport(app=create_app(allowing))

    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
        ours = await client.get("/health", headers={"Origin": "https://lustjinn.example"})
        theirs = await client.get("/health", headers={"Origin": "https://somewhere.example"})
        # The browser's question before a request that carries the token: "may I send this?"
        preflight = await client.options(
            "/stories",
            headers={
                "Origin": "https://lustjinn.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

    assert ours.headers["Access-Control-Allow-Origin"] == "https://lustjinn.example"
    assert "Access-Control-Allow-Origin" not in theirs.headers
    assert preflight.status_code == 200
    assert "authorization" in preflight.headers["Access-Control-Allow-Headers"].lower()
    assert "Access-Control-Allow-Credentials" not in ours.headers
