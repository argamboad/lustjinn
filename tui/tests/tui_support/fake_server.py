"""A stand-in for the Lustjinn API behind httpx2's ``MockTransport``: the routes the client uses,
answered from memory, with switches for the failures the screens must survive.

The tests script a server the way the API's tests script a model: set the state, run the client,
read what it asked for.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx2

TOKEN = "t0ken"
USERNAME = "allan"
PASSWORD = "secret"


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


def story(name: str, *texts: str, character: str = "Dummy") -> dict[str, Any]:
    messages = [
        message(i + 1, "assistant" if i % 2 == 0 else "user", text) for i, text in enumerate(texts)
    ]
    last = messages[-1] if messages else None
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "character_id": str(uuid.uuid4()),
        "character_name": character,
        "persona_id": None,
        "persona_name": "Me",
        "model": None,
        "created_at": datetime(2026, 10, 1, tzinfo=UTC).isoformat(),
        "last_message_at": last["sent_at"] if last else None,
        "last_message_preview": last["text"][:80] if last else None,
        "messages": messages,
    }


def sse(name: str, data: object) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()


class FakeServer:
    def __init__(self) -> None:
        self.asleep_for = 0  # health calls that fail before the server "wakes"
        self.down = False  # every call fails, as if the network were gone
        self.valid_tokens: set[str] = {TOKEN}
        self.stories: list[dict[str, Any]] = []
        self.requests: list[httpx2.Request] = []
        self.reply = "She looks up. *A pause.*"
        self.reply_pieces = 3

    # -- scripting ------------------------------------------------------------------------------

    def add(self, name: str, *texts: str) -> dict[str, Any]:
        added = story(name, *texts)
        self.stories.append(added)
        return added

    def revoke(self) -> None:
        self.valid_tokens.clear()

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.handle)

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
        if path == "/stories" and request.method == "GET":
            listed = [{k: v for k, v in s.items() if k != "messages"} for s in self.stories]
            return httpx2.Response(200, json=listed)
        parts = path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "stories":
            found = next((s for s in self.stories if s["id"] == parts[1]), None)
            if found is None:
                return httpx2.Response(404, json={"detail": "There is no such story."})
            if len(parts) == 2 and request.method == "GET":
                return httpx2.Response(200, json=found)
            if len(parts) == 3 and parts[2] in {"send", "continue", "reroll"}:
                return self._turn(found, request)
        return httpx2.Response(404, json={"detail": f"Nothing answers {request.method} {path}."})

    def _turn(self, found: dict[str, Any], request: httpx2.Request) -> httpx2.Response:
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        sent = None
        if "text" in body:
            sent = message(len(found["messages"]) + 1, "user", body["text"])
            found["messages"].append(sent)
        reply = message(len(found["messages"]) + 1, "assistant", self.reply)
        found["messages"].append(reply)
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
