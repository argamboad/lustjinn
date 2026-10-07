"""The client's one way to the outside: the Lustjinn API over HTTP, nothing else.

airp's terminal called its services in-process; this one only speaks to the same API the PWA
uses, so the same stories are playable from either. The shapes are pydantic models of the API's
responses (the TypeScript interfaces of ``web/src/lib/api.ts``, in Python); a refusal becomes an
``ApiError`` carrying the API's own sentence, a server that cannot be reached becomes
``UnreachableError``, and a ``401`` becomes ``SignedOutError`` — three different things to a screen.

A turn is a POST that streams server-sent events: ``delta`` as the text arrives, then one
``done`` or ``error``. httpx2's ``EventSource`` cuts the stream into events; this module types
them.

.NET readers: a typed ``HttpClient`` wrapper with ``System.Text.Json`` records, and
``HttpCompletionOption.ResponseHeadersRead`` for the stream.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, cast

import httpx2
from pydantic import BaseModel, Field, TypeAdapter

from lustjinn_tui.config import TokenStore

# -- errors ------------------------------------------------------------------------------------


class ApiError(Exception):
    """The API answered, and refused. ``detail`` is its own sentence."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class SignedOutError(ApiError):
    """A 401: no token, or one the API no longer accepts. The token is forgotten."""


class UnreachableError(Exception):
    """No answer at all: the server is asleep, down, or the network is."""


# -- shapes ------------------------------------------------------------------------------------


class Health(BaseModel):
    status: str
    commit: str | None = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


Role = Literal["user", "assistant", "system"]


class Message(BaseModel):
    id: uuid.UUID
    sequence: int
    role: Role
    text: str
    model: str | None = None
    provider: str | None = None
    fell_back_from: str | None = None
    sent_at: datetime


class Story(BaseModel):
    id: uuid.UUID
    name: str
    character_id: uuid.UUID
    character_name: str
    persona_id: uuid.UUID | None = None
    persona_name: str | None = None
    model: str | None = None
    created_at: datetime
    last_message_at: datetime | None = None
    last_message_preview: str | None = None


class StoryWithMessages(Story):
    messages: list[Message]


Shelf = Literal["characters", "personas", "snippets"]


class Entry(BaseModel):
    """A library entry as a list shows it: the name and a taste of the text."""

    id: uuid.UUID
    name: str
    hidden: bool = False
    version: int
    updated_at: datetime
    preview: str


class EntryFull(Entry):
    text: str
    opening: str | None = None
    used_by: list[str] = Field(default_factory=list)


class Defaults(BaseModel):
    default_persona_id: uuid.UUID | None = None
    default_persona_name: str | None = None


class Cut(BaseModel):
    """What deleting from a message left behind."""

    story: StoryWithMessages
    hidden: int
    summaries_removed: int = 0
    facts_removed: int = 0
    facts_reopened: int = 0


class StorySpend(BaseModel):
    """What one story has cost: the priced calls, and the share rerolled or cut away."""

    story_id: uuid.UUID
    name: str
    calls: int
    cost: Decimal
    discarded_calls: int = 0
    discarded_cost: Decimal = Decimal(0)
    unpriced: int = 0


class Choice(BaseModel):
    """A model to pick, with the provider's list prices beside it — to compare by only."""

    id: str
    is_default: bool = False
    listed: bool = True
    context_length: int | None = None
    prompt_per_million: Decimal | None = None
    completion_per_million: Decimal | None = None
    prompt_price_ratio: Decimal | None = None

    def describe(self) -> str:
        """``id`` with how its prompt price compares with the default's (``ModelInfo.Describe``
        in the donor): ≥1.5× "≈N× the default", ≤0.67× "≈1/N of the default", else nothing."""
        if self.is_default or self.prompt_price_ratio is None:
            return self.id
        ratio = self.prompt_price_ratio
        if ratio >= Decimal("1.5"):
            return f"{self.id}  ≈{ratio.quantize(Decimal(1))}× the default"
        if ratio <= Decimal("0.67") and ratio > 0:
            return f"{self.id}  ≈1/{(1 / ratio).quantize(Decimal(1))} of the default"
        return f"{self.id}  about the default"


class Aside(BaseModel):
    id: uuid.UUID
    sequence: int
    question: str
    answer: str
    model: str | None = None
    provider: str | None = None
    asked_at: datetime


class Delta(BaseModel):
    """A piece of the reply, as it arrives."""

    text: str


class TurnDone(BaseModel):
    kind: Literal["turn"] = "turn"
    sent: Message | None = None
    reply: Message
    replayed: bool = False


class AsideDone(BaseModel):
    kind: Literal["aside"] = "aside"
    aside: Aside


class Said(BaseModel):
    """An answer shown once and stored nowhere: a recap, a tracker set by hand."""

    kind: Literal["said"] = "said"
    text: str


class Failed(BaseModel):
    kind: Literal["error"] = "error"
    detail: str
    sent: Message | None = None


Done = Annotated[TurnDone | AsideDone | Said | Failed, Field(discriminator="kind")]
Event = Delta | TurnDone | AsideDone | Said | Failed

_stories = TypeAdapter(list[Story])
_entries = TypeAdapter(list[Entry])
_choices = TypeAdapter(list[Choice])
_done = TypeAdapter[TurnDone | AsideDone | Said | Failed](Done)


# -- the client --------------------------------------------------------------------------------


class Api:
    def __init__(
        self,
        server: str,
        tokens: TokenStore,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.server = server
        self._tokens = tokens
        self._client = httpx2.AsyncClient(
            base_url=server,
            transport=transport,
            timeout=httpx2.Timeout(30.0, read=180.0),  # a reply can take its time
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def signed_in(self) -> bool:
        return self._tokens.read() is not None

    def _headers(self) -> dict[str, str]:
        token = self._tokens.read()
        return {"Authorization": f"Bearer {token}"} if token else {}

    # -- plumbing -------------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: object | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        try:
            response = await self._client.request(
                method, path, json=json, params=params, headers=self._headers()
            )
        except httpx2.TransportError as error:
            raise UnreachableError(str(error)) from error
        self._check(response.status_code, response)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _check(self, status: int, response: httpx2.Response) -> None:
        if status < 400:
            return
        detail = _detail(response)
        if status == 401:
            self._tokens.forget()
            raise SignedOutError(status, detail)
        raise ApiError(status, detail)

    async def _stream(self, method: str, path: str, json: object | None) -> AsyncIterator[Event]:
        try:
            async with self._client.stream(
                method, path, json=json, headers=self._headers()
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    self._check(response.status_code, response)
                async for event in httpx2.EventSource(response):
                    if event.event == "delta":
                        yield Delta.model_validate_json(event.data)
                    elif event.event in {"done", "error"}:
                        yield _done.validate_json(event.data)
        except httpx2.TransportError as error:
            raise UnreachableError(str(error)) from error

    # -- open to anyone ---------------------------------------------------------------------

    async def health(self) -> Health:
        return Health.model_validate(await self._request("GET", "/health"))

    async def sign_in(self, username: str, password: str) -> Token:
        issued = Token.model_validate(
            await self._request(
                "POST", "/auth/sign-in", json={"username": username, "password": password}
            )
        )
        self._tokens.write(issued.access_token)
        return issued

    def sign_out(self) -> None:
        self._tokens.forget()

    # -- stories ------------------------------------------------------------------------------

    async def stories(self) -> list[Story]:
        return _stories.validate_python(await self._request("GET", "/stories"))

    async def story(self, story_id: uuid.UUID) -> StoryWithMessages:
        return StoryWithMessages.model_validate(await self._request("GET", f"/stories/{story_id}"))

    async def create_story(
        self,
        name: str,
        character_id: uuid.UUID,
        persona_id: uuid.UUID | None = None,
        model: str | None = None,
    ) -> StoryWithMessages:
        body: dict[str, object] = {"name": name, "character_id": str(character_id)}
        if persona_id is not None:
            body["persona_id"] = str(persona_id)
        if model is not None:
            body["model"] = model
        return StoryWithMessages.model_validate(await self._request("POST", "/stories", json=body))

    async def rename_story(self, story_id: uuid.UUID, name: str) -> Story:
        return Story.model_validate(
            await self._request("PATCH", f"/stories/{story_id}", json={"name": name})
        )

    async def delete_story(self, story_id: uuid.UUID) -> None:
        await self._request("DELETE", f"/stories/{story_id}")

    async def branch(
        self, story_id: uuid.UUID, message_id: uuid.UUID, name: str | None = None
    ) -> StoryWithMessages:
        """A copy of the story up to that message, under ``name`` or one the server picks."""
        return StoryWithMessages.model_validate(
            await self._request(
                "POST",
                f"/stories/{story_id}/branch",
                json={"message_id": str(message_id), "name": name},
            )
        )

    async def delete_from(self, story_id: uuid.UUID, message_id: uuid.UUID) -> Cut:
        return Cut.model_validate(
            await self._request("DELETE", f"/stories/{story_id}/messages/{message_id}")
        )

    async def story_spend(self, story_id: uuid.UUID) -> StorySpend:
        return StorySpend.model_validate(await self._request("GET", f"/stories/{story_id}/spend"))

    # -- the library ---------------------------------------------------------------------------

    async def entries(self, shelf: Shelf) -> list[Entry]:
        return _entries.validate_python(await self._request("GET", f"/library/{shelf}"))

    async def entry(self, shelf: Shelf, entry_id: uuid.UUID) -> EntryFull:
        return EntryFull.model_validate(await self._request("GET", f"/library/{shelf}/{entry_id}"))

    async def defaults(self) -> Defaults:
        return Defaults.model_validate(await self._request("GET", "/library/settings"))

    # -- models -------------------------------------------------------------------------------

    async def models(self) -> list[Choice]:
        """The default first, then the configured choices."""
        return _choices.validate_python(await self._request("GET", "/models"))

    # -- turns: streamed --------------------------------------------------------------------

    def send(self, story_id: uuid.UUID, text: str) -> AsyncIterator[Event]:
        return self._stream("POST", f"/stories/{story_id}/send", {"text": text})

    def carry_on(self, story_id: uuid.UUID) -> AsyncIterator[Event]:
        return self._stream("POST", f"/stories/{story_id}/continue", None)

    def reroll(
        self, story_id: uuid.UUID, reason: str | None = None, instructions: str | None = None
    ) -> AsyncIterator[Event]:
        body: dict[str, str] = {}
        if reason:
            body["reason"] = reason
        if instructions:
            body["instructions"] = instructions
        return self._stream("POST", f"/stories/{story_id}/reroll", body)


def _detail(response: httpx2.Response) -> str:
    """The API's sentence, from FastAPI's ``{"detail": …}``; the status text when there is none."""
    try:
        body: object = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"
    if isinstance(body, dict):
        typed = cast(dict[str, object], body)
        detail = typed.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list):  # a validation error: one line per field
            items = cast(list[object], detail)
            parts = [
                str(cast(dict[str, object], item)["msg"])
                for item in items
                if isinstance(item, dict) and "msg" in cast(dict[str, object], item)
            ]
            if parts:
                return "; ".join(parts)
    return response.text.strip() or f"HTTP {response.status_code}"
