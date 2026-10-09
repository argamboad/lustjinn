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


def message(sequence: int, role: str, text: str) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "sequence": sequence,
        "role": role,
        "text": text,
        "model": "scripted/model" if role == "assistant" else None,
        "provider": None,
        "sent_at": datetime(2026, 10, 7, 9, sequence % 60, tzinfo=UTC).isoformat(),
    }


def story(
    name: str,
    *texts: str,
    character: str = "Dummy",
    character_id: str | None = None,
    persona_id: str | None = None,
    persona: str | None = "Me",
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
        self.pack: list[dict[str, Any]] = [
            {
                "key": "lust",
                "kind": "scale",
                "lever": "prompt",
                "maps": None,
                "enabled": True,
                "default": None,
                "title": "Lust",
                "help": "The story's current arousal level — heat only. Pace lives in pacing.",
                "levels": [
                    {"label": "Cold", "text": "detached", "value": None, "description": None},
                    {"label": "Friendly", "text": "warm", "value": None, "description": None},
                    {"label": "Flirty", "text": "playful", "value": None, "description": None},
                    {"label": "Explicit", "text": "forward", "value": None, "description": None},
                    {"label": "Unhinged", "text": "no limits", "value": None, "description": None},
                ],
                "options": [],
                "on_text": None,
                "template": None,
                "accepts": None,
                "examples": [],
            },
            {
                "key": "inner-thoughts",
                "kind": "toggle",
                "lever": "prompt",
                "maps": None,
                "enabled": True,
                "default": "false",
                "title": "Inner thoughts",
                "help": "Whether the character's thoughts are written in italics.",
                "levels": [],
                "options": [],
                "on_text": "show thoughts",
                "template": None,
                "accepts": None,
                "examples": [],
            },
            {
                "key": "pov",
                "kind": "choice",
                "lever": "prompt",
                "maps": None,
                "enabled": True,
                "default": None,
                "title": "Point of view",
                "help": "Narrative person and tense. Unset follows the card.",
                "levels": [],
                "options": [
                    {
                        "key": "second-present",
                        "label": "Second person, present",
                        "text": "second, present",
                    },
                    {"key": "third-past", "label": "Third limited, past", "text": "third, past"},
                ],
                "on_text": None,
                "template": None,
                "accepts": None,
                "examples": [],
            },
            {
                "key": "language",
                "kind": "text",
                "lever": "prompt",
                "maps": None,
                "enabled": True,
                "default": None,
                "title": "Language",
                "help": "The language the replies are written in.",
                "levels": [],
                "options": [],
                "on_text": None,
                "template": "Write in {value}.",
                "accepts": "a language",
                "examples": ["Spanish"],
            },
            {
                "key": "agency-guard",
                "kind": "scale",
                "lever": "prompt",
                "maps": None,
                "enabled": False,
                "default": None,
                "title": "Agency guard",
                "help": "Disabled in the pack.",
                "levels": [
                    {"label": f"L{i}", "text": None, "value": None, "description": None}
                    for i in range(5)
                ],
                "options": [],
                "on_text": None,
                "template": None,
                "accepts": None,
                "examples": [],
            },
        ]
        self.dial_values: dict[str, dict[str, str]] = {}  # story id -> key -> value
        self.requests: list[httpx2.Request] = []
        self.reply = "She looks up. *A pause.*"
        self.reply_pieces = 3
        self.model_fails: str | None = None  # the model's failure, as the API's error event
        self.facts: dict[str, list[dict[str, Any]]] = {}  # story id -> facts
        self.trackers: dict[str, list[dict[str, Any]]] = {}
        self.audits: dict[str, dict[str, Any]] = {}
        self.answer = "She is twenty-nine; the story said so in the second scene."
        self.commands_unreadable = False  # GET /commands fails, as on a cold start
        self.commands: list[dict[str, Any]] = [
            {
                "name": "do",
                "usage": "/do <direction>",
                "summary": "Steer",
                "cost": "billed",
                "needs_argument": True,
            },
            {
                "name": "focus",
                "usage": "/focus <who>",
                "summary": "Hand over",
                "cost": "billed",
                "needs_argument": True,
            },
            {
                "name": "ask",
                "usage": "/ask <question>",
                "summary": "Ask",
                "cost": "billed",
                "needs_argument": True,
            },
            {
                "name": "recap",
                "usage": "/recap [turns]",
                "summary": "Recap",
                "cost": "free",
                "needs_argument": False,
            },
            {
                "name": "fact",
                "usage": "/fact <statement>",
                "summary": "Pin",
                "cost": "write",
                "needs_argument": True,
            },
            {
                "name": "tracker",
                "usage": "/tracker <name> <value>",
                "summary": "Set",
                "cost": "write",
                "needs_argument": True,
            },
        ]
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
        if path == "/commands":
            if self.commands_unreadable:
                return httpx2.Response(503, json={"detail": "Not now."})
            return httpx2.Response(200, json=self.commands)
        if path == "/search":
            return self._search(request)
        if path == "/dials":
            return httpx2.Response(200, json=self.pack)
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
        if len(parts) == 3 and parts[2] == "facts" and request.method == "GET":
            listed = self.facts.get(found["id"], [])
            if request.url.params.get("all") != "true":
                listed = [f for f in listed if f["valid_to_sequence"] is None]
            return httpx2.Response(200, json=listed)
        if len(parts) == 3 and parts[2] == "facts" and request.method == "POST":
            body = json.loads(request.content)
            fact = {
                "id": str(uuid.uuid4()),
                "subject": body["subject"],
                "text": body["text"],
                "valid_from_sequence": len(found["messages"]),
                "valid_to_sequence": None,
                "model": None,
                "pinned": True,
            }
            self.facts.setdefault(found["id"], []).append(fact)
            return httpx2.Response(201, json=fact)
        if len(parts) == 3 and parts[2] == "trackers" and request.method == "GET":
            return httpx2.Response(200, json=self.trackers.get(found["id"], []))
        if len(parts) == 3 and parts[2] == "audit":
            return httpx2.Response(
                200, json=self.audits.get(found["id"], {"turns": [], "asides": []})
            )
        if len(parts) >= 3 and parts[2] == "dials":
            return self._dials(found, parts, request)
        if len(parts) == 3 and parts[2] == "export":
            return self._export(found, request)
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
        texts = (character["opening"],) if character.get("opening") else ()
        created = self.add(
            str(body["name"]),
            *texts,
            character=character["name"],
            character_id=character["id"],
            persona_id=None if persona is None else persona["id"],
            persona=None if persona is None else persona["name"],
            created_at=datetime(2026, 10, 7, 12, tzinfo=UTC),
        )
        return httpx2.Response(201, json=created)

    def _library(self, parts: list[str], request: httpx2.Request) -> httpx2.Response:
        if parts[1:] == ["settings"]:
            if request.method == "PUT":
                body = json.loads(request.content)
                wanted = body.get("default_persona_id")
                self.default_persona = (
                    None
                    if wanted is None
                    else next(p for p in self.library["personas"] if p["id"] == wanted)
                )
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
        kind = parts[1][:-1]
        if len(parts) == 2 and request.method == "GET":
            summaries = [
                {k: v for k, v in e.items() if k not in {"text", "opening", "used_by"}}
                for e in shelf
            ]
            return httpx2.Response(200, json=summaries)
        if len(parts) == 2 and request.method == "POST":
            body = json.loads(request.content)
            if any(e["name"].lower() == body["name"].lower() for e in shelf):
                return httpx2.Response(
                    409,
                    json={
                        "detail": f"A {kind} called '{body['name']}' already exists. Edit it, "
                        "or pick another name."
                    },
                )
            created = self.shelve(parts[1], body["name"], body["text"], body.get("opening"))
            return httpx2.Response(201, json=created)
        found = next((e for e in shelf if e["id"] == parts[2]), None) if len(parts) > 2 else None
        if found is None:
            return httpx2.Response(404, json={"detail": "There is no such entry."})
        if len(parts) == 3 and request.method == "GET":
            users = [
                s["name"]
                for s in self.stories
                if (parts[1] == "characters" and s["character_id"] == found["id"])
                or (parts[1] == "personas" and s["persona_id"] == found["id"])
            ]
            return httpx2.Response(200, json={**found, "used_by": users})
        if len(parts) == 3 and request.method == "PATCH":
            body = json.loads(request.content)
            if body["version"] != found["version"]:
                return httpx2.Response(
                    409,
                    json={
                        "detail": {
                            "message": f"This {kind} changed somewhere else since you opened "
                            "it. Nothing was saved. Here is what it says now; save again to "
                            "replace it.",
                            "current": found,
                        }
                    },
                )
            changed = False
            for field in ("name", "text", "opening"):
                if field in body and body[field] != found.get(field):
                    found[field] = body[field]
                    changed = True
            if changed:
                found["version"] += 1
                found["preview"] = found["text"][:200]
            return httpx2.Response(200, json=found)
        if len(parts) == 3 and request.method == "DELETE":
            users = [
                s["name"]
                for s in self.stories
                if (parts[1] == "characters" and s["character_id"] == found["id"])
                or (parts[1] == "personas" and s["persona_id"] == found["id"])
            ]
            if users:
                return httpx2.Response(
                    409,
                    json={
                        "detail": f"This {kind} is used by {', '.join(users)}. It stays until "
                        "they do not."
                    },
                )
            shelf.remove(found)
            return httpx2.Response(204)
        return httpx2.Response(404, json={"detail": f"Nothing answers {request.method} {parts}."})

    def _dial_out(self, dial: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
        stored = values.get(dial["key"])
        effective = stored if dial["enabled"] and stored is not None else dial["default"]
        label = None
        if effective is not None:
            if dial["kind"] == "scale":
                label = dial["levels"][int(effective)]["label"]
            elif dial["kind"] == "toggle":
                label = "On" if effective == "true" else "Off"
            elif dial["kind"] == "choice":
                label = next(o["label"] for o in dial["options"] if o["key"] == effective)
            else:
                label = effective
        return {
            "key": dial["key"],
            "title": dial["title"],
            "kind": dial["kind"],
            "enabled": dial["enabled"],
            "stored": stored,
            "effective": effective,
            "label": label,
        }

    def _dials(
        self, found: dict[str, Any], parts: list[str], request: httpx2.Request
    ) -> httpx2.Response:
        values = self.dial_values.setdefault(found["id"], {})
        if len(parts) == 3 and request.method == "GET":
            return httpx2.Response(200, json=[self._dial_out(d, values) for d in self.pack])
        dial = (
            next((d for d in self.pack if d["key"] == parts[3]), None) if len(parts) == 4 else None
        )
        if dial is None:
            return httpx2.Response(404, json={"detail": "There is no such dial."})
        if request.method == "DELETE":
            values.pop(dial["key"], None)
            return httpx2.Response(204)
        if not dial["enabled"]:
            return httpx2.Response(
                409,
                json={
                    "detail": f"{dial['title']} is disabled in the pack, so it is pinned to "
                    "its default."
                },
            )
        value = str(json.loads(request.content)["value"]).strip()
        accepted: str | None
        if dial["kind"] == "scale":
            accepted = value if value.isdigit() and int(value) < len(dial["levels"]) else None
        elif dial["kind"] == "toggle":
            accepted = value.lower() if value.lower() in {"true", "false"} else None
        elif dial["kind"] == "choice":
            accepted = value if any(o["key"] == value for o in dial["options"]) else None
        else:
            accepted = value or None
        if accepted is None:
            return httpx2.Response(422, json={"detail": f"{dial['title']} takes something else."})
        values[dial["key"]] = accepted
        return httpx2.Response(200, json=self._dial_out(dial, values))

    def _export(self, found: dict[str, Any], request: httpx2.Request) -> httpx2.Response:
        fmt = request.url.params.get("format", "markdown")
        ext = {"markdown": "md", "json": "json", "text": "txt"}.get(fmt)
        if ext is None:
            return httpx2.Response(422, json={"detail": "format: not a known format"})
        turns: list[dict[str, Any]] = found["messages"]
        if fmt == "json":
            document = json.dumps({"title": found["name"], "messages": turns}, indent=2)
        elif fmt == "text":
            document = "\n\n".join(f"[{m['sequence']:03d}] {m['role']}\n{m['text']}" for m in turns)
        else:
            document = f"# {found['name']}\n\n" + "\n\n".join(
                f"## {m['sequence']}. {m['role']}\n\n{m['text']}" for m in turns
            )
        slug = found["name"].lower().replace(" ", "-")
        filename = f"transcript-{slug}-20261007-120000.{ext}"
        return httpx2.Response(
            200,
            headers={
                "content-type": "text/plain; charset=utf-8",
                "content-disposition": f'attachment; filename="{filename}"',
            },
            content=document.encode(),
        )

    def _search(self, request: httpx2.Request) -> httpx2.Response:
        query = request.url.params.get("q", "").lower()
        within = request.url.params.get("story_id")
        hits: list[dict[str, Any]] = []
        for s in self.stories:
            if within is not None and s["id"] != within:
                continue
            if within is None and query in s["name"].lower():
                hits.append(
                    {
                        "scope": "name",
                        "story_id": s["id"],
                        "story_name": s["name"],
                        "snippet": s["name"],
                        "score": 100,
                    }
                )
            for m in s["messages"]:
                if query in m["text"].lower():
                    hits.append(
                        {
                            "scope": "message",
                            "story_id": s["id"],
                            "story_name": s["name"],
                            "message_id": m["id"],
                            "sequence": m["sequence"],
                            "role": m["role"],
                            "speaker": "You" if m["role"] == "user" else s["character_name"],
                            "sent_at": m["sent_at"],
                            "snippet": m["text"][:96],
                            "score": 40,
                        }
                    )
        return httpx2.Response(200, json={"hits": hits, "searched": len(self.stories)})

    def _turn(self, found: dict[str, Any], request: httpx2.Request) -> httpx2.Response:
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        messages: list[dict[str, Any]] = found["messages"]
        kind = request.url.path.rsplit("/", 1)[-1]
        if kind == "send" and str(body.get("text", "")).startswith("/"):
            return self._command(found, str(body["text"]))
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

    def _command(self, found: dict[str, Any], text: str) -> httpx2.Response:
        """The API's own commands, as `/send` answers them: a turn, an aside, a word, or a
        refusal before anything streams."""
        if text.startswith("//"):
            return self._prose(found, text[1:])
        name, _, argument = text[1:].partition(" ")
        argument = argument.strip()
        known = {c["name"]: c for c in self.commands}
        if name not in known:
            return httpx2.Response(
                422,
                json={
                    "detail": f"/{name} is not a command, so nothing was sent and nothing was "
                    "stored. To send a line that begins with a slash, begin it with two."
                },
            )
        if known[name]["needs_argument"] and not argument:
            return httpx2.Response(
                422, json={"detail": f"Usage: {known[name]['usage']} — nothing was stored."}
            )
        stream = {"content-type": "text/event-stream"}
        if name == "ask":
            aside = {
                "id": str(uuid.uuid4()),
                "sequence": len(found["messages"]),
                "question": argument,
                "answer": self.answer,
                "model": "scripted/model",
                "provider": None,
                "asked_at": datetime(2026, 10, 7, 10, tzinfo=UTC).isoformat(),
            }
            return httpx2.Response(
                200, headers=stream, content=self._single("done", {"kind": "aside", "aside": aside})
            )
        if name == "recap":
            text = "Earlier: the fog came in.\n\n" + "\n\n".join(
                f"{'You' if m['role'] == 'user' else found['character_name']}: {m['text']}"
                for m in found["messages"][-4:]
            )
            return httpx2.Response(
                200, headers=stream, content=self._single("done", {"kind": "said", "text": text})
            )
        if name == "fact":
            self.facts.setdefault(found["id"], []).append(
                {
                    "id": str(uuid.uuid4()),
                    "subject": found["character_name"],
                    "text": argument,
                    "valid_from_sequence": len(found["messages"]),
                    "valid_to_sequence": None,
                    "model": None,
                    "pinned": True,
                }
            )
            said = (
                f"Pinned under {found['character_name']}. It is in every prompt from the next "
                "turn on."
            )
            return httpx2.Response(
                200, headers=stream, content=self._single("done", {"kind": "said", "text": said})
            )
        if name == "tracker":
            meter, _, value = argument.rpartition(" ")
            try:
                number = float(value)
            except ValueError:
                return httpx2.Response(
                    422,
                    json={
                        "detail": "/tracker <name> <value> — the value has to be a number, so "
                        "nothing was stored."
                    },
                )
            return httpx2.Response(
                200,
                headers=stream,
                content=self._single(
                    "done", {"kind": "said", "text": f"{meter} is now {number:g}."}
                ),
            )
        # /do and /focus: a reply with nothing from the reader, or a message under a direction.
        message_text = None
        if name == "do" and "\n\n" in argument:
            _, _, message_text = argument.partition("\n\n")
        return self._prose(found, message_text)

    def _prose(self, found: dict[str, Any], text: str | None) -> httpx2.Response:
        messages: list[dict[str, Any]] = found["messages"]
        sent = None
        if text is not None:
            sent = message(len(messages) + 1, "user", text)
            messages.append(sent)
        reply = message(len(messages) + 1, "assistant", self.reply)
        messages.append(reply)
        found["last_message_at"] = reply["sent_at"]
        found["last_message_preview"] = reply["text"][:200]
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=self._events(sent, reply)
        )

    async def _single(self, name: str, data: object) -> AsyncIterator[bytes]:
        yield sse(name, data)
