"""Sign-in for the one user, and the guard every other endpoint sits behind.

The client signs in once with the username and password and receives a signed token (a JWT). It
sends the token back in the `Authorization: Bearer …` header of every request. Nothing is stored
on the server: the signature proves the token is ours and the expiry inside it says until when.
A header rather than a cookie because the web client and the API will live on different sites.
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, SecretStr

from lustjinn.settings import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])

ALGORITHM = "HS256"  # one secret both signs and verifies; only this server ever does either
CurrentSettings = Annotated[Settings, Depends(get_settings)]


class Credentials(BaseModel):
    username: str
    password: SecretStr


class Token(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime


def sign(claims: dict[str, object], secret: str, algorithm: str = ALGORITHM) -> str:
    """Encodes the claims as a JWT signed with the secret."""
    return jwt.encode(claims, secret, algorithm=algorithm)  # pyright: ignore[reportUnknownMemberType]


def verify(token: str, secret: str) -> dict[str, object]:
    """Returns the claims of a token we signed that has not expired; raises otherwise.

    Naming the one algorithm we accept is what defeats a token that claims to need no signature.
    """
    return jwt.decode(  # pyright: ignore[reportUnknownMemberType]
        token, secret, algorithms=[ALGORITHM], options={"require": ["sub", "exp"]}
    )


def issue_token(settings: Settings, now: datetime | None = None) -> Token:
    """A token for the one user, valid for `token_days` from `now`."""
    issued = now or datetime.now(UTC)
    expires = issued + timedelta(days=settings.token_days)
    encoded = sign(
        {"sub": settings.username, "iat": issued, "exp": expires},
        settings.token_secret.get_secret_value(),
    )
    return Token(access_token=encoded, expires_at=expires)


def _same(given: str, expected: str) -> bool:
    """Compares in constant time, so the time taken does not reveal how much matched."""
    return secrets.compare_digest(given.encode(), expected.encode())


def _refuse(why: str) -> HTTPException:
    # WWW-Authenticate is what a 401 is required to carry: it names the scheme to use.
    return HTTPException(status.HTTP_401_UNAUTHORIZED, why, {"WWW-Authenticate": "Bearer"})


@router.post("/sign-in")
async def sign_in(credentials: Credentials, settings: CurrentSettings) -> Token:
    """Exchanges the username and password for a bearer token."""
    # Both are checked before deciding, and the answer never says which one was wrong.
    name_matches = _same(credentials.username, settings.username)
    password_matches = _same(
        credentials.password.get_secret_value(), settings.password.get_secret_value()
    )
    if not (name_matches and password_matches):
        raise _refuse("Wrong username or password.")
    return issue_token(settings)


# auto_error=False: a missing header reaches require_user, which answers with our own 401.
_bearer = HTTPBearer(auto_error=False, description="The token from POST /auth/sign-in.")


async def require_user(
    presented: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: CurrentSettings,
) -> str:
    """Lets the request through only with a valid, unexpired token. Returns the username."""
    if presented is None:
        raise _refuse("Sign in first: this needs a bearer token.")
    try:
        claims = verify(presented.credentials, settings.token_secret.get_secret_value())
    except jwt.ExpiredSignatureError:
        raise _refuse("The token has expired. Sign in again.") from None
    except jwt.InvalidTokenError:
        raise _refuse("The token is not valid. Sign in again.") from None
    if claims["sub"] != settings.username:
        raise _refuse("The token is not valid. Sign in again.")
    return settings.username
