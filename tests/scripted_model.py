"""A model that answers from a script instead of the network, in OpenRouter's own stream format.

Every test that needs a model uses this, through the `model` fixture. It records what each call
sent, so a test can assert on the prompt, the model, the temperature — and fails the way the real
one does: a status with an error body, a 200 with nothing in it, a reply cut off at the ceiling.
"""

import hashlib
import json
from collections import deque
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Self

import httpx2

from lustjinn.openrouter import OpenRouter
from lustjinn.settings import Settings

Json = dict[str, Any]


def _sse(chunks: list[Json]) -> str:
    """OpenRouter's stream: a keep-alive comment, one `data:` line per chunk, then `[DONE]`."""
    lines = [": OPENROUTER PROCESSING\n\n"]
    lines += [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks]
    lines.append("data: [DONE]\n\n")
    return "".join(lines)


def _chunk(generation: str, model: str, provider: str | None, **more: Any) -> Json:
    chunk: Json = {"id": generation, "object": "chat.completion.chunk", "model": model, **more}
    if provider is not None:
        chunk["provider"] = provider
    return chunk


def _delta(generation: str, model: str, provider: str | None, content: str) -> Json:
    return _chunk(
        generation,
        model,
        provider,
        choices=[{"index": 0, "delta": {"role": "assistant", "content": content}}],
    )


KEYWORDS = ("ferrin", "dock", "knife", "silver")
"""The axes of the test embedder: a text's vector says which of these words it contains. Two
texts that share a word are near; texts with none of them all point the same, harmless way."""

DIMENSIONS = 1536


def keyword_vector(text: str) -> list[float]:
    """A deterministic stand-in for an embedding: one axis per keyword. A text with none of them
    points along an axis of its own, chosen from its hash, so two unrelated texts are orthogonal
    rather than identical — and no vector is zero (cosine distance to zero is undefined)."""
    lowered = text.lower()
    vector = [0.0] * DIMENSIONS
    found = False
    for axis, word in enumerate(KEYWORDS):
        if word in lowered:
            vector[axis] = 1.0
            found = True
    if not found:
        digest = int(hashlib.sha256(text.encode()).hexdigest(), 16)
        vector[len(KEYWORDS) + digest % (DIMENSIONS - len(KEYWORDS))] = 1.0
    return vector


def a_listed_model(model_id: str, context_length: int | None, prompt: str, completion: str) -> Json:
    """One entry of OpenRouter's model list: an id, a window, and prices per token as strings."""
    entry: Json = {"id": model_id, "pricing": {"prompt": prompt, "completion": completion}}
    if context_length is not None:
        entry["context_length"] = context_length
    return entry


class ScriptedModel:
    """A queue of answers, each consumed by one call."""

    def __init__(self) -> None:
        self._answers: deque[Callable[[], httpx2.Response]] = deque()
        self.calls: list[Json] = []
        """The body of every chat request that reached the model, in order."""
        self.requests: list[httpx2.Request] = []
        self.embedding_calls: list[list[str]] = []
        """The texts of every embedding request, in order."""
        self.embedder_down = False
        """When True, the embeddings endpoint answers 503 — the chat endpoint still works."""
        self.embedding_dimensions = DIMENSIONS
        self.listing: list[Json] = [
            a_listed_model("deepseek/deepseek-v4-flash", 128_000, "0.00000014", "0.00000028"),
            a_listed_model("test-model", 32_000, "0.0000005", "0.000001"),
        ]
        """What GET /models answers: the default and the test model, priced. A test that needs
        another model adds it with `lists(...)`."""
        self.catalogue_down = False
        """When True, GET /models answers 503."""

    @property
    def last(self) -> Json:
        return self.calls[-1]

    def says(
        self,
        text: str,
        *,
        model: str = "test-model",
        provider: str | None = "test-host",
        cost: Decimal | None = Decimal("0.0002"),
        prompt_tokens: int = 10,
        completion_tokens: int = 5,
        cached_tokens: int | None = 4,
        finish_reason: str = "stop",
    ) -> Self:
        """Answers `text`, streamed in pieces, with usage and cost in the final chunk."""
        generation = f"gen-{len(self._answers) + len(self.calls) + 1}"
        usage: Json = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        if cost is not None:
            usage["cost"] = float(cost)
        if cached_tokens is not None:
            usage["prompt_tokens_details"] = {"cached_tokens": cached_tokens}
        # Split mid-sentence on purpose: a client that only handled whole words would pass a
        # test with one chunk and garble a real reply.
        cut = max(1, len(text) // 2)
        chunks = [
            _delta(generation, model, provider, text[:cut]),
            _delta(generation, model, provider, text[cut:]),
            _chunk(
                generation,
                model,
                provider,
                choices=[{"index": 0, "delta": {}, "finish_reason": finish_reason}],
            ),
            _chunk(generation, model, provider, choices=[], usage=usage),
        ]
        return self._queue(lambda: self._stream(chunks))

    def summarises(self, gist: str) -> Self:
        """Answers a summary that passes the credibility floor: the gist, padded with the kind
        of sentence a real summary carries."""
        padding = (
            " Rowan took room seven and paid for a week. Isaure wrote the name in the ledger "
            "without looking up. Blake watched the door from the corner table."
        )
        return self.says(gist + padding * 4)

    def extracts(
        self,
        facts: list[tuple[str, str]] = [],  # noqa: B006 — read only
        retired: list[str] = [],  # noqa: B006
        *,
        fenced: bool = False,
    ) -> Self:
        """Answers the fact extractor's JSON: new facts as (subject, text), and ids to retire.
        `fenced` wraps it in a Markdown code fence, as chatty models do."""
        document = json.dumps(
            {"facts": [{"subject": s, "text": t} for s, t in facts], "retired": retired}
        )
        return self.says(f"```json\n{document}\n```" if fenced else document)

    def lists(self, *models: Json) -> Self:
        """Adds models to what GET /models answers; see `a_listed_model`."""
        self.listing.extend(models)
        return self

    def says_unpriced(self, text: str) -> Self:
        """Answers without the API saying what it charged, as some hosts do."""
        return self.says(text, provider=None, cost=None, cached_tokens=None)

    def truncated(self, text: str) -> Self:
        """Answers a few words and reports that it was cut off at the ceiling."""
        return self.says(text, finish_reason="length", prompt_tokens=4000, completion_tokens=20)

    def empty(self) -> Self:
        """Fails the way a host does when it answers 200 and sends nothing."""
        generation = "gen-empty"
        chunks = [
            _chunk(
                generation,
                "test-model",
                "test-host",
                choices=[{"index": 0, "delta": {"role": "assistant"}, "finish_reason": "stop"}],
            ),
            _chunk(generation, "test-model", "test-host", choices=[], usage={"prompt_tokens": 10}),
        ]
        return self._queue(lambda: self._stream(chunks))

    def reasons_only(self) -> Self:
        """Spends the whole ceiling thinking and writes nothing."""
        generation = "gen-thought"
        chunks = [
            _chunk(
                generation,
                "test-model",
                "test-host",
                choices=[{"index": 0, "delta": {"reasoning": "Let me think about"}}],
            ),
            _chunk(
                generation,
                "test-model",
                "test-host",
                choices=[{"index": 0, "delta": {}, "finish_reason": "length"}],
            ),
        ]
        return self._queue(lambda: self._stream(chunks))

    def fails(self, message: str = "the provider is down", status: int = 503) -> Self:
        """Refuses with a status and OpenRouter's error body."""
        return self._queue(
            lambda: httpx2.Response(status, json={"error": {"code": status, "message": message}})
        )

    def rejected(self) -> Self:
        """Fails in a way no second attempt could fix: the key was refused."""
        return self.fails("No auth credentials found", 401)

    def has_no_such_model(self) -> Self:
        """Refuses the way OpenRouter does a model no host serves."""
        return self.fails("No endpoints found for the model.", 404)

    def breaks_mid_stream(self, message: str = "Provider returned error") -> Self:
        """Starts answering, then sends an error chunk, as a host dying mid-reply does."""
        generation = "gen-broken"
        chunks = [
            _delta(generation, "test-model", "test-host", "She was about to"),
            {"id": generation, "error": {"code": 502, "message": message}},
        ]
        return self._queue(lambda: self._stream(chunks))

    def not_json(self) -> Self:
        return self._queue(lambda: httpx2.Response(200, text="<html>gateway</html>"))

    def transport(self) -> httpx2.MockTransport:
        """What stands in for the network: records the request, pops the next answer."""

        def handle(request: httpx2.Request) -> httpx2.Response:
            self.requests.append(request)
            if request.url.path.endswith("/embeddings"):
                return self._embed(json.loads(request.content))
            if request.url.path.endswith("/models") and request.method == "GET":
                if self.catalogue_down:
                    return httpx2.Response(503, json={"error": {"code": 503, "message": "down"}})
                return httpx2.Response(200, json={"data": self.listing})
            if request.content:
                self.calls.append(json.loads(request.content))
            if not self._answers:
                raise AssertionError("The model was called with nothing scripted for it.")
            return self._answers.popleft()()

        return httpx2.MockTransport(handle)

    def client(self, settings: Settings) -> OpenRouter:
        return OpenRouter(settings, httpx2.AsyncClient(transport=self.transport()))

    def _embed(self, body: Json) -> httpx2.Response:
        texts: list[str] = body["input"]
        self.embedding_calls.append(texts)
        if self.embedder_down:
            return httpx2.Response(503, json={"error": {"code": 503, "message": "embedder down"}})
        data = [
            {"index": i, "embedding": keyword_vector(text)[: self.embedding_dimensions]}
            for i, text in enumerate(texts)
        ]
        return httpx2.Response(200, json={"data": data, "model": body["model"]})

    def _queue(self, answer: Callable[[], httpx2.Response]) -> Self:
        self._answers.append(answer)
        return self

    @staticmethod
    def _stream(chunks: list[Json]) -> httpx2.Response:
        return httpx2.Response(
            200, content=_sse(chunks).encode(), headers={"content-type": "text/event-stream"}
        )
