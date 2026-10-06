# CLAUDE.md

> Operating manual for Claude Code on this project. Auto-loaded each session — keep it tight.

## What this project is
**Lustjinn** is a web app for NSFW roleplay with a memory that does not forget: a Python rebuild of
the good parts of airp (`argamboad/custom-airp`, .NET 10). **The full brief is `docs/KICKOFF.md` —
read it whole before the first task of a session.** It holds the decided stack, the data-model
sketch, the lessons airp paid for, and the roadmap.

## How to work here
- **The goal is learning Python as a backend**, not shipping. The owner is an experienced
  C#/.NET developer: explain Python by **mapping it to the .NET equivalent** (ASP.NET Core, EF Core,
  xUnit, `IOptions<T>`…).
- **Claude writes the code; the course teaches it.** `docs/course/` (built to a PDF) explains each
  step as it is built, mapped to .NET. Each step's chapter is its own issue and its own commit, in
  that step's PR — a step is not done until its chapter is.
- **The web UI is dark and light, designed, and approved by the owner** before the screens are
  built and again when done (GitHub #75). The terminal client is dark by design, no gate.
- **custom-airp is the donor of logic.** Before building a feature, read its donor files and tests
  as listed in `docs/DONOR.md` and in the issue's *Donor* note.
- **Do not invent and do not assume.** If a fact is missing, ask.
- **The lessons in `docs/KICKOFF.md` are binding.** Do not re-learn them; if a task seems to
  contradict one, stop and say so.
- **Never commit secrets.** They live in Render environment variables and a local `.env`
  (gitignored).

## Commands
- `uv sync` — environment from `uv.lock`. Python is pinned in `.python-version` (3.14).
- `docker compose up -d` — the local Postgres (17 + pgvector, port 5440). The tests need it: they
  create their own throwaway database on it and never touch the `lustjinn` one.
- `uv run alembic upgrade head` — apply the migrations. A schema change is a model edit **and** a
  migration (`uv run alembic revision --autogenerate -m "…"`, then read and tidy it); a test fails
  when the two disagree. Database rules a model cannot express (triggers) are hand-written SQL in
  a migration.
- `uv run python scripts/seed_dummy.py` — the dummy character and persona, for playing locally.
  Tests that need a character use the `dummy` fixture, never a few inline words.
- **A test that scripts a summary also scripts the fact extraction that follows it**
  (`model.summarises(…).extracts(…).says(…)`), or the extractor eats the reply meant for the
  reader. The ledger then holds `summary`, `facts` and `reply` rows.
- `uv run uvicorn lustjinn.main:app --reload` — the API locally; settings come from `.env`
  (see `.env.example`).
- **Token counting needs the network once:** tiktoken downloads `o200k_base` from
  `openaipublic.blob.core.windows.net` on first use and caches it. A cloud environment with a
  Custom allowlist must include that domain, or the tests cannot count.
- **The gates, all clean before any commit:** `uv run pytest`, `uv run ruff check`,
  `uv run ruff format --check`, `uv run pyright` (strict).
- **The web app lives in `web/`** (SvelteKit 5, static, a PWA): `npm ci` once, `npm run dev`
  for the dev server against the local API, and its gates — `npm run lint` (prettier),
  `npm run check` (svelte-check), `npm test` (vitest), `npm run build` — all clean before any
  commit. The design tokens are `web/src/lib/theme.css`; every colour is a token defined for
  both themes, and no component names a colour of its own. `node scripts/icons.mjs` renders the
  icon set from `brand/logo.svg` when the logo changes.

## Workflow
- **One PR per roadmap step, one commit per issue.** Branch `step/N-…` from `develop`; each issue of
  the step is exactly one commit (its message says `Closes #N`), the course chapter included. Open the
  PR when every issue of the step is in it.
- **After each merge, stop.** Sync `develop`, delete the merged branch (locally and on GitHub),
  report where things stand, and wait for the owner to choose what comes next. No autopilot: never
  start the next issue or step unasked, and never stack a PR on an unmerged one.

## Tracking
- **Every piece of work has a GitHub issue**, in the milestone of its roadmap step
  (`Step N · …`). Work found along the way gets a new issue in the step's milestone — and its own
  commit.
- Labels follow the sibling repos: `type/*`, `area/*`, `needs-decision`, `owner/you`.

## Repository
- `origin` is **GitHub** (`https://github.com/argamboad/lustjinn.git`, private); issues, PRs and
  merges happen there, with `gh`.
- **`develop` is the default branch: branch from it, and every PR merges into it. `main` is for
  releases only.**
- **Actions minutes are billed.** CI runs on PRs and on `main` pushes, never on a `develop` push.
  Say what a run costs before triggering one by hand.
- Old commit messages cite issue numbers from the retired Forgejo tracker; a migrated issue's
  footer names its Forgejo number.
