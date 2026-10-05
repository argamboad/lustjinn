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
uv run uvicorn lustjinn.main:app --reload   # http://127.0.0.1:8000/health, /docs
```

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
