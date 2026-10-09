"""The model, reached through OpenRouter: one OpenAI-compatible endpoint, one key, many models.

Replies are streamed. The request says `stream: true`; the response is server-sent events, each
carrying a piece of the text, and the last carrying what the call cost. Nothing here is specific
to OpenRouter beyond three things: the `provider` routing field, the `reasoning` switch, and the
`usage.cost` figure — all of which are the reasons for choosing it.
"""

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Literal

import httpx2
from fastapi import Depends

from lustjinn import sse
from lustjinn.settings import Settings, get_settings

Role = Literal["system", "user", "assistant"]


class ModelError(Exception):
    """The model did not answer. The message is fit to show the reader; the status helps code."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True, kw_only=True)
class Reply:
    """What the model wrote, and what the call cost. The last thing a stream yields."""

    text: str
    model: str | None
    """The model that answered, as the API reported it — a router may serve another build."""
    provider: str | None
    """The host that served it, by display name (`DeepInfra`). Hosts differ in price, caching
    and willingness; when a reply reads oddly this is the first thing worth knowing."""
    generation_id: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    cached_tokens: int | None
    """Prompt tokens served from the host's cache: the measurement that says whether the prompt's
    layer order is doing its job."""
    cache_write_tokens: int | None
    cost: Decimal | None
    """What the router charged, read from the response. None means it did not say — which is
    not the same as zero. Never computed here from a price list."""
    finish_reason: str | None

    @property
    def truncated(self) -> bool:
        """Stopped at the token ceiling rather than at the end of what it had to say."""
        return self.finish_reason == "length"


@lru_cache
def get_http() -> httpx2.AsyncClient:
    """One HTTP client for the process: it owns the connection pool, like the database engine."""
    return httpx2.AsyncClient()


async def close_http() -> None:
    if get_http.cache_info().currsize:
        await get_http().aclose()
        get_http.cache_clear()


class OpenRouter:
    """A client for one OpenAI-compatible chat endpoint. Built per request, over the shared pool."""

    def __init__(self, settings: Settings, http: httpx2.AsyncClient) -> None:
        self._settings = settings
        self._http = http

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        frequency_penalty: float | None = None,
        reasoning: bool | None = None,
    ) -> AsyncIterator[str | Reply]:
        """Asks for a completion and yields it as it arrives: pieces of text, then the `Reply`.

        Every failure is a `ModelError`. A 200 that carries no text is one too: an empty string
        stored as a reply would be a turn that never happened.
        """
        if not messages:
            raise ValueError("A completion needs at least one message.")
        settings = self._settings
        body: dict[str, object] = {
            "model": model or settings.model,
            "stream": True,
            "temperature": settings.temperature if temperature is None else temperature,
            "max_tokens": settings.max_tokens if max_tokens is None else max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        # Only when asked for: to some backends, zero and absent are different requests, and
        # only absent means "no opinion".
        if frequency_penalty is not None:
            body["frequency_penalty"] = frequency_penalty
        # OpenRouter's own field, so only when asked. A model that cannot switch its reasoning
        # off refuses the call with a 400 that says so.
        if reasoning is not None:
            body["reasoning"] = {"enabled": reasoning}
        if (routing := self._routing()) is not None:
            body["provider"] = routing

        text: list[str] = []
        answered_model: str | None = None
        provider: str | None = None
        generation_id: str | None = None
        finish_reason: str | None = None
        usage: dict[str, object] | None = None
        reasoned = False

        async with self._request("POST", "chat/completions", body) as response:
            kind = response.headers.get("content-type", "")
            if not kind.startswith("text/event-stream"):
                # A gateway's HTML page, say. Reading it as a stream would find no events and
                # report "no content", which would send the reader after the wrong problem.
                raise ModelError(f"The API returned a body that is not a stream ({kind or '?'}).")
            async for event in sse.events(response.aiter_lines()):
                if event.data == "[DONE]":
                    break
                chunk = _parse(event.data)
                # An error after the stream has begun arrives as a chunk, not as a status.
                if (error := _object(chunk, "error")) is not None:
                    said = _string(error, "message") or ""
                    raise ModelError(
                        f"The API reported an error mid-stream. {said}".strip(),
                        _integer(error, "code"),
                    )
                answered_model = _string(chunk, "model") or answered_model
                provider = _string(chunk, "provider") or provider
                generation_id = _string(chunk, "id") or generation_id
                for choice in _objects(chunk, "choices"):
                    delta = _object(choice, "delta") or {}
                    if piece := _string(delta, "content"):
                        text.append(piece)
                        yield piece
                    if delta.get("reasoning") is not None:
                        reasoned = True
                    finish_reason = _string(choice, "finish_reason") or finish_reason
                usage = _object(chunk, "usage") or usage

        if not "".join(text).strip():
            # Named in as much detail as the response allows: finish_reason separates a filter
            # from a ceiling hit before the first token from a host with nothing to say, and a
            # reasoning field with no content is a model that spent everything thinking.
            why = finish_reason or "absent"
            served = f", served by {provider}" if provider else ""
            thought = ", reasoning only" if reasoned else ""
            raise ModelError(
                f"The API returned a response with no message content "
                f"(finish_reason: {why}{served}{thought}).",
                200,
            )

        details = _object(usage or {}, "prompt_tokens_details") or {}
        yield Reply(
            text="".join(text),
            model=answered_model,
            provider=provider,
            generation_id=generation_id,
            prompt_tokens=_integer(usage or {}, "prompt_tokens"),
            completion_tokens=_integer(usage or {}, "completion_tokens"),
            cached_tokens=_integer(details, "cached_tokens"),
            cache_write_tokens=_integer(details, "cache_write_tokens"),
            cost=_decimal(usage or {}, "cost"),
            finish_reason=finish_reason,
        )

    async def complete(self, messages: Sequence[ChatMessage], **options: object) -> Reply:
        """The whole reply at once, for callers with nothing to show while it is written."""
        async for piece in self.stream(messages, **options):  # pyright: ignore[reportArgumentType]
            if isinstance(piece, Reply):
                return piece
        raise ModelError("The stream ended without a reply.")  # the generator always yields one

    async def embed(self, texts: Sequence[str], *, model: str) -> list[list[float]]:
        """One vector per text, in the order given. Every failure is a `ModelError`.

        OpenRouter's /embeddings speaks OpenAI's shape: `{model, input: [...]}` in,
        `data[].embedding` with `data[].index` out. The index is what the order is read from —
        a host may answer in any order.
        """
        if not texts:
            return []
        body: dict[str, object] = {"model": model, "input": list(texts), "encoding_format": "float"}
        async with self._request("POST", "embeddings", body) as response:
            answer = _parse((await response.aread()).decode())
        found: dict[int, list[float]] = {}
        for entry in _objects(answer, "data"):
            index = _integer(entry, "index")
            vector = entry.get("embedding")
            if index is None or not isinstance(vector, list):
                continue
            found[index] = [float(x) for x in vector]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        if len(found) != len(texts):
            raise ModelError(
                f"The embeddings API returned {len(found)} vectors for {len(texts)} texts.", 200
            )
        return [found[i] for i in range(len(texts))]

    def _routing(self) -> dict[str, object] | None:
        """OpenRouter's `provider` object, or None when nothing is configured.

        Omitted entirely rather than sent empty: it is the one field in the request that is not
        OpenAI's. Slugs go out trimmed and otherwise as given — the router drops one it does not
        know without complaint, so lower-casing to be helpful would only hide a typo.
        """
        settings = self._settings
        order = [p.strip() for p in settings.prefer_providers if p.strip()]
        ignore = [p.strip() for p in settings.ignore_providers if p.strip()]
        if not order and not ignore and settings.allow_provider_fallbacks is None:
            return None
        routing: dict[str, object] = {}
        if order:
            routing["order"] = order
        if ignore:
            routing["ignore"] = ignore
        if settings.allow_provider_fallbacks is not None:
            routing["allow_fallbacks"] = settings.allow_provider_fallbacks
        return routing

    def _request(self, method: str, route: str, body: dict[str, object] | None = None):
        """One call, with every transport failure turned into a `ModelError` that says why."""
        return _Call(self._settings, self._http, method, route, body)


class _Call:
    """`async with` around one HTTP request: opens it, checks the status, closes it after."""

    def __init__(
        self,
        settings: Settings,
        http: httpx2.AsyncClient,
        method: str,
        route: str,
        body: dict[str, object] | None,
    ) -> None:
        self._settings = settings
        self._http = http
        self._method = method
        self._route = route
        self._body = body
        self._response: httpx2.Response | None = None

    async def __aenter__(self) -> httpx2.Response:
        settings = self._settings
        if settings.openrouter_api_key is None:
            raise ModelError(
                "No OpenRouter API key is configured (LUSTJINN_OPENROUTER_API_KEY).", 401
            )
        request = self._http.build_request(
            self._method,
            f"{settings.openrouter_base_url.rstrip('/')}/{self._route}",
            json=self._body,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key.get_secret_value()}",
                # OpenRouter reads these for attribution on its dashboards. Harmless elsewhere.
                "HTTP-Referer": "https://github.com/argamboad/lustjinn",
                "X-Title": "Lustjinn",
            },
            # The one timeout, in one place: to connect, and between one chunk and the next. A
            # streaming reply that keeps arriving is alive however long it takes as a whole.
            timeout=httpx2.Timeout(settings.model_timeout_seconds),
        )
        try:
            response = await self._http.send(request, stream=True)
        except httpx2.TimeoutException:
            raise ModelError(
                f"The model did not answer within {settings.model_timeout_seconds}s."
            ) from None
        except httpx2.HTTPError as error:
            raise ModelError(f"Could not reach {settings.openrouter_base_url}: {error}") from error
        self._response = response
        if response.status_code >= 400:
            # Only the message out of the body, never the body itself: an error body can echo
            # the request back, and the request is the story.
            explained = _explain(await response.aread())
            await response.aclose()
            status = f"{response.status_code} {response.reason_phrase}"
            raise ModelError(
                f"The API returned {status}. {explained}".strip(), response.status_code
            )
        return response

    async def __aexit__(self, *_: object) -> None:
        if self._response is not None:
            await self._response.aclose()


def _explain(content: bytes) -> str:
    try:
        body = _parse(content.decode())
    except ModelError:
        return ""
    return _string(_object(body, "error") or {}, "message") or ""


# JSON comes back as `Any`; these narrow it one field at a time, so pyright knows what it holds.

Json = dict[str, object]


def _parse(text: str) -> Json:
    try:
        parsed: object = json.loads(text, parse_float=Decimal)  # money is read as Decimal
    except json.JSONDecodeError:
        raise ModelError("The API returned a body that is not JSON.") from None
    return parsed if isinstance(parsed, dict) else {}  # pyright: ignore[reportUnknownVariableType]


def _object(source: Json, key: str) -> Json | None:
    value = source.get(key)
    return value if isinstance(value, dict) else None  # pyright: ignore[reportUnknownVariableType]


def _objects(source: Json, key: str) -> list[Json]:
    value = source.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]  # pyright: ignore[reportUnknownVariableType]


def _string(source: Json, key: str) -> str | None:
    value = source.get(key)
    return value if isinstance(value, str) else None


def _integer(source: Json, key: str) -> int | None:
    value = source.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _decimal(source: Json, key: str) -> Decimal | None:
    value = source.get(key)
    if isinstance(value, Decimal):
        return value
    return Decimal(value) if isinstance(value, int) and not isinstance(value, bool) else None


def get_openrouter(settings: Annotated[Settings, Depends(get_settings)]) -> OpenRouter:
    """The client an endpoint asks for. Tests override this with one that answers from a script."""
    return OpenRouter(settings, get_http())
