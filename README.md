# Lustjinn

A web app for roleplay with a memory that does not forget — a Python successor to **airp**
(`argamboad/custom-airp`, .NET 10).

> You do not need an infinite context window if you have a good retrieval layer.

The real goal is learning Python as a backend. Stack, decisions, lessons carried over from airp and
the roadmap: [`docs/KICKOFF.md`](docs/KICKOFF.md).

## Running it

Needs [uv](https://docs.astral.sh/uv/), which fetches the pinned Python by itself, and Docker for
the database.

```
cp .env.example .env                        # then fill in the blanks
docker compose up -d                        # Postgres 17 + pgvector on localhost:5440
uv sync                                     # create .venv from uv.lock
uv run alembic upgrade head                 # create or update the tables
uv run python scripts/seed_dummy.py         # optional: a dummy character and persona to play with
uv run uvicorn lustjinn.main:app --reload   # http://127.0.0.1:8000/health, /docs
```

The web app lives in `web/` (SvelteKit 5, static, installable as a PWA). With the API running and
`LUSTJINN_CORS_ORIGINS=["http://localhost:5173"]` in `.env`:

```
cd web
npm ci                                      # once
npm run dev                                 # http://localhost:5173 — sign in with the API's user
```

Its gates are `npm run lint`, `npm run check`, `npm test` and `npm run build`. It follows the
system theme and remembers a switch; add it to a phone's home screen to install it.

Sign in with `POST /auth/sign-in`; every other endpoint needs the token it returns. On `/docs`,
press **Authorize** and paste it. The docs are served only when `LUSTJINN_DOCS=true` (it is, in
`.env.example`); a deployed API leaves them off. Five wrong sign-ins within fifteen minutes lock
sign-in for the rest of the window, even with the right password, and each wrong one is answered
a second late.

Playing needs an OpenRouter key in `.env` (`LUSTJINN_OPENROUTER_API_KEY`). `POST /stories/{id}/send`
takes what the reader typed and streams the reply back as server-sent events. The slash commands
are read before anything is stored: `/ask <question>` asks about the story out of character,
`/do <direction>` steers the next reply (alone, or over a message after a blank line), `/focus
<who>` hands the turn to a named character, `/recap [turns]` shows the story so far for free,
`/tracker <name> <value>` moves a meter by hand, and anything else is refused. `POST
/stories/{id}/continue` has the model write the next beat with nothing from the reader; `POST
/stories/{id}/reroll` writes the newest reply again, with an optional reason and guidance.

How a story is written is set per story: `/dials` lists the pack and `/stories/{id}/dials` holds
the story's values (each dial reaches the prompt or the sampler, never the transcript);
`/stories/{id}/trackers` holds its meters, drawn by the model at the end of each reply and read
back; `/models` lists the models a story may play on with their prices, and `PUT
/stories/{id}/model` changes the story's — checked against the provider's list and the model's
window first, and falling back to the default on a turn it cannot take.

A story can be taken two ways or cut back: `POST /stories/{id}/branch` copies it up to a turn with the memory those turns built, and `DELETE /stories/{id}/messages/{message_id}` hides a turn and everything after it, memory included — the rows stay. `GET /search?q=` finds where a phrase was said, across stories or inside one; `GET /stories/{id}/export?format=` renders the transcript as Markdown, JSON or text; `GET /spend` and `GET /stories/{id}/spend` report what the ledger holds, discarded replies and unpriced calls told apart. `/stories/{id}/facts` lists, pins and retires what the story believes (`/fact <statement>` pins from the composer); `POST /stories/{id}/memory/rebuild` makes the summaries and facts again from the transcript; and `POST /stories/{id}/purge` erases a deleted story for good, keeping only its spend.

The library is under `/library/{characters|personas|snippets}`: list, create, read, save (with
the version the editor started from), delete (refused while a story uses the entry), and each
entry's history. `/library/settings` names the default persona. A `:name` in a message expands
to the snippet of that name before it is stored.

## The gates

```
uv run pytest
uv run ruff check
uv run ruff format --check
uv run pyright
```

## Tracking

One GitHub milestone per roadmap step, with an issue for each piece of work. `develop` is the
default branch and every pull request merges into it; `main` is for releases only.
