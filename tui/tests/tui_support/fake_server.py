"""A stand-in for the Lustjinn API behind httpx2's ``MockTransport``: the routes the client uses,
answered from memory, with switches for the failures the screens must survive.

The tests script a server the way the API's tests script a model: set the state, run the client,
read what it asked for.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2

TOKEN = "t0ken"
USERNAME = "allan"
PASSWORD = "secret"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"


def message(sequence: int, role: str, text: str) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "sequence": sequence,
        "role": role,
        "text": text,
        "model": "scripted/model" if role == "assistant" else None,
        "provider": None,
        "fell_back_from": None,
        "sent_at": datetime(2026, 10, 7, 9, sequence % 60, tzinfo=UTC).isoformat(),
    }


def story(
    name: str,
    *texts: str,
    character: str = "Dummy",
    character_id: str | None = None,
    persona_id: str | None = None,
    persona: str | None = "Me",
    model: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    messages = [
        message(i + 1, "assistant" if i % 2 == 0 else "user", text) for i, text in enumerate(texts)
    ]
    last = messages[-1] if messages else None
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "character_id": character_id or str(uuid.uuid4()),
        "character_name": character,
        "persona_id": persona_id,
        "persona_name": persona,
        "model": model,
        "created_at": (created_at or datetime(2026, 10, 1, tzinfo=UTC)).isoformat(),
        "last_message_at": last["sent_at"] if last else None,
        "last_message_preview": last["text"][:200] if last else None,
        "messages": messages,
    }


def entry(name: str, text: str, opening: str | None = None) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "hidden": False,
        "version": 1,
        "updated_at": datetime(2026, 10, 1, tzinfo=UTC).isoformat(),
        "preview": text[:200],
        "text": text,
        "opening": opening,
        "used_by": [],
    }


def choice(model: str, *, is_default: bool = False, ratio: str | None = None) -> dict[str, Any]:
    return {
        "id": model,
        "is_default": is_default,
        "listed": True,
        "context_length": 128000,
        "prompt_per_million": "0.1",
        "completion_per_million": "0.3",
        "prompt_price_ratio": ratio,
    }


def sse(name: str, data: object) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()


class FakeServer:
    def __init__(self) -> None:
        self.asleep_for = 0  # health calls that fail before the server "wakes"
        self.down = False  # every call fails, as if the network were gone
        self.valid_tokens: set[str] = {TOKEN}
        self.stories: list[dict[str, Any]] = []
        self.library: dict[str, list[dict[str, Any]]] = {
            "characters": [],
            "personas": [],
            "snippets": [],
        }
        self.default_persona: dict[str, Any] | None = None
        self.models: list[dict[str, Any]] = [
            choice(DEFAULT_MODEL, is_default=True),
            choice("thedrummer/anubis-70b", ratio="2.00"),
            choice("mistralai/mistral-small", ratio="0.50"),
        ]
        self.models_unreadable = False
        self.requests: list[httpx2.Request] = []
        self.reply = "She looks up. *A pause.*"
        self.reply_pieces = 3
        self.model_fails: str | None = None  # the model's failure, as the API's error event
        self.reroll_bodies: list[dict[str, Any]] = []
        self.spend: dict[str, tuple[str, str]] = {}  # story id -> (cost, discarded)

    # -- scripting ------------------------------------------------------------------------------

    def add(self, name: str, *texts: str, **fields: Any) -> dict[str, Any]:
        """A story, newest first in the list as the API orders them."""
        if "created_at" not in fields:
            fields["created_at"] = datetime(2026, 10, 1, tzinfo=UTC) + timedelta(
                hours=len(self.stories)
            )
        added = story(name, *texts, **fields)
        self.stories.append(added)
        return added

    def shelve(
        self, shelf: str, name: str, text: str, opening: str | None = None
    ) -> dict[str, Any]:
        added = entry(name, text, opening)
        self.library[shelf].append(added)
        return added

    def revoke(self) -> None:
        self.valid_tokens.clear()

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

    def paths(self, method: str | None = None) -> list[str]:
        """What was asked for, in order: ``["GET /stories", …]`` or the paths of one method."""
        return [
            f"{r.method} {r.url.path}" if method is None else r.url.path
            for r in self.requests
            if method is None or r.method == method
        ]

    # -- the routes -------------------------------------------------------------------------

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.down:
            raise httpx2.ConnectError("connection refused", request=request)
        path = request.url.path
        if path == "/health":
            if self.asleep_for > 0:
                self.asleep_for -= 1
                raise httpx2.ConnectError("asleep", request=request)
            return httpx2.Response(200, json={"status": "ok", "commit": None})
        if path == "/auth/sign-in":
            body: dict[str, Any] = json.loads(request.content)
            if body.get("username") == USERNAME and body.get("password") == PASSWORD:
                self.valid_tokens.add(TOKEN)
                return httpx2.Response(
                    200,
                    json={
                        "access_token": TOKEN,
                        "token_type": "bearer",
                        "expires_at": "2026-11-06T00:00:00Z",
                    },
                )
            return httpx2.Response(401, json={"detail": "That is not the username and password."})
        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if token not in self.valid_tokens:
            return httpx2.Response(401, json={"detail": "The token is not valid. Sign in again."})
        parts = path.strip("/").split("/")
        if parts[0] == "stories":
            return self._stories(parts, request)
        if parts[0] == "library":
            return self._library(parts, request)
        if path == "/models":
            if self.models_unreadable:
                return httpx2.Response(
                    503, json={"detail": "The model list could not be read: timed out."}
                )
            return httpx2.Response(200, json=self.models)
        return httpx2.Response(404, json={"detail": f"Nothing answers {request.method} {path}."})

    @staticmethod
    def _listed(found: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in found.items() if k != "messages"}

    def _stories(self, parts: list[str], request: httpx2.Request) -> httpx2.Response:
        if len(parts) == 1 and request.method == "GET":
            ordered = sorted(
                self.stories, key=lambda s: s["last_message_at"] or s["created_at"], reverse=True
            )
            return httpx2.Response(200, json=[self._listed(s) for s in ordered])
        if len(parts) == 1 and request.method == "POST":
            return self._create(json.loads(request.content))
        found = next((s for s in self.stories if s["id"] == parts[1]), None)
        if found is None:
            return httpx2.Response(404, json={"detail": "There is no such story."})
        if len(parts) == 2 and request.method == "GET":
            return httpx2.Response(200, json=found)
        if len(parts) == 2 and request.method == "PATCH":
            body: dict[str, Any] = json.loads(request.content)
            name = str(body.get("name", "")).strip()
            if not name:
                return httpx2.Response(422, json={"detail": "name: a name is needed"})
            found["name"] = name
            return httpx2.Response(200, json=self._listed(found))
        if len(parts) == 2 and request.method == "DELETE":
            self.stories.remove(found)
            return httpx2.Response(204)
        if len(parts) == 3 and parts[2] in {"send", "continue", "reroll"}:
            return self._turn(found, request)
        if len(parts) == 3 and parts[2] == "spend":
            cost, discarded = self.spend.get(found["id"], ("0", "0"))
            calls = sum(1 for m in found["messages"] if m["role"] == "assistant" and m["model"])
            return httpx2.Response(
                200,
                json={
                    "story_id": found["id"],
                    "name": found["name"],
                    "calls": calls,
                    "cost": cost,
                    "discarded_calls": 0,
                    "discarded_cost": discarded,
                    "unpriced": 0,
                },
            )
        if len(parts) == 3 and parts[2] == "branch" and request.method == "POST":
            body = json.loads(request.content)
            index = next(
                (i for i, m in enumerate(found["messages"]) if m["id"] == body["message_id"]),
                None,
            )
            if index is None:
                return httpx2.Response(404, json={"detail": "There is no such message."})
            taken = {s["name"] for s in self.stories}
            n = 2
            while f"{found['name']} ({n})" in taken:
                n += 1
            name = body.get("name") or f"{found['name']} ({n})"
            copy = self.add(
                name,
                *(m["text"] for m in found["messages"][: index + 1]),
                character=found["character_name"],
                character_id=found["character_id"],
                created_at=datetime(2026, 10, 7, 13, tzinfo=UTC),
            )
            return httpx2.Response(201, json=copy)
        if len(parts) == 4 and parts[2] == "messages" and request.method == "DELETE":
            index = next((i for i, m in enumerate(found["messages"]) if m["id"] == parts[3]), None)
            if index is None:
                return httpx2.Response(404, json={"detail": "There is no such message."})
            hidden = len(found["messages"]) - index
            del found["messages"][index:]
            last = found["messages"][-1] if found["messages"] else None
            found["last_message_at"] = last["sent_at"] if last else None
            found["last_message_preview"] = last["text"][:200] if last else None
            return httpx2.Response(
                200,
                json={
                    "story": found,
                    "hidden": hidden,
                    "summaries_removed": 0,
                    "facts_removed": 0,
                    "facts_reopened": 0,
                },
            )
        return httpx2.Response(404, json={"detail": f"Nothing answers {request.method} {parts}."})

    def _create(self, body: dict[str, Any]) -> httpx2.Response:
        character = next(
            (c for c in self.library["characters"] if c["id"] == body.get("character_id")), None
        )
        if character is None:
            return httpx2.Response(422, json={"detail": "There is no character with that id."})
        persona = None
        if body.get("persona_id"):
            persona = next(
                (p for p in self.library["personas"] if p["id"] == body["persona_id"]), None
            )
            if persona is None:
                return httpx2.Response(422, json={"detail": "There is no persona with that id."})
        model = body.get("model")
        if model is not None and model not in {m["id"] for m in self.models}:
            return httpx2.Response(
                422,
                json={
                    "detail": f"{model} is not available — the provider does not list it — so "
                    f"it was not set. The story stays on {DEFAULT_MODEL}."
                },
            )
        texts = (character["opening"],) if character.get("opening") else ()
        created = self.add(
            str(body["name"]),
            *texts,
            character=character["name"],
            character_id=character["id"],
            persona_id=None if persona is None else persona["id"],
            persona=None if persona is None else persona["name"],
            model=model,
            created_at=datetime(2026, 10, 7, 12, tzinfo=UTC),
        )
        return httpx2.Response(201, json=created)

    def _library(self, parts: list[str], request: httpx2.Request) -> httpx2.Response:
        if parts[1:] == ["settings"]:
            default = self.default_persona
            return httpx2.Response(
                200,
                json={
                    "default_persona_id": None if default is None else default["id"],
                    "default_persona_name": None if default is None else default["name"],
                },
            )
        shelf = self.library.get(parts[1]) if len(parts) > 1 else None
        if shelf is None:
            return httpx2.Response(404, json={"detail": "There is no such shelf."})
        if len(parts) == 2 and request.method == "GET":
            summaries = [
                {k: v for k, v in e.items() if k not in {"text", "opening", "used_by"}}
                for e in shelf
            ]
            return httpx2.Response(200, json=summaries)
        found = next((e for e in shelf if e["id"] == parts[2]), None) if len(parts) > 2 else None
        if found is None:
            return httpx2.Response(404, json={"detail": "There is no such entry."})
        if len(parts) == 3 and request.method == "GET":
            return httpx2.Response(200, json=found)
        return httpx2.Response(404, json={"detail": f"Nothing answers {request.method} {parts}."})

    def _turn(self, found: dict[str, Any], request: httpx2.Request) -> httpx2.Response:
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        messages: list[dict[str, Any]] = found["messages"]
        kind = request.url.path.rsplit("/", 1)[-1]
        if kind == "reroll":
            last = messages[-1] if messages else None
            if last is None or last["role"] != "assistant":
                return httpx2.Response(
                    409,
                    json={
                        "detail": "There is no reply to write again: a reroll applies to the "
                        "newest reply. Send a message first."
                    },
                )
            if last["model"] is None and not any(m["role"] == "user" for m in messages):
                return httpx2.Response(
                    409,
                    json={
                        "detail": "The opening is not rerolled: a person wrote it. Write your "
                        "first turn; the reply to it can be rerolled."
                    },
                )
            self.reroll_bodies.append(body)
            messages.pop()  # hidden on the server, kept for the record
        if kind == "continue" and not any(m["role"] == "assistant" for m in messages):
            return httpx2.Response(409, json={"detail": "There is no reply to carry on from."})
        sent = None
        if kind == "send":
            sent = message(len(messages) + 1, "user", body["text"])
            messages.append(sent)
        if self.model_fails is not None:
            return httpx2.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=self._failure(sent, self.model_fails),
            )
        reply = message(len(messages) + 1, "assistant", self.reply)
        messages.append(reply)
        found["last_message_at"] = reply["sent_at"]
        found["last_message_preview"] = reply["text"][:200]
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=self._events(sent, reply),
        )

    async def _events(
        self, sent: dict[str, Any] | None, reply: dict[str, Any]
    ) -> AsyncIterator[bytes]:
        text = reply["text"]
        size = max(1, len(text) // self.reply_pieces)
        for at in range(0, len(text), size):
            yield sse("delta", {"text": text[at : at + size]})
        yield sse("done", {"kind": "turn", "sent": sent, "reply": reply, "replayed": False})

    async def _failure(self, sent: dict[str, Any] | None, detail: str) -> AsyncIterator[bytes]:
        yield sse("error", {"kind": "error", "detail": detail, "sent": sent})
