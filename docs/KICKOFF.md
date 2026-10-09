# Kickoff — an airp successor, in Python

A brief for starting this project in a new repository and a new session. Read it whole before the
first task. It carries over the decisions already made and the lessons a previous project paid for,
so they are not re-learned.

---

## What this is

An app for **NSFW roleplay with a memory that does not forget**, built as a side project that
takes the good parts of **airp** (`argamboad/custom-airp`, .NET 10) and rebuilds them in Python:
one API, and two clients that play the same stories — a web app and a terminal client.

**The real goal is learning: Python, especially as a backend.** Shipping matters less than
understanding. The owner is an experienced C#/.NET developer (ASP.NET Core, EF Core, xUnit), so:

- Explain Python by **mapping it to the .NET equivalent** he already knows.
- Claude writes the code, and a course explains it (see *Settled before step 1*, below).
- **One change at a time**, confirmed before moving on. **Do not invent and do not assume**: if a
  fact is missing, ask.

The thesis carried over from airp:

> You do not need an infinite context window if you have a good retrieval layer.

---

## Decided

| Layer | Choice | Why |
|---|---|---|
| Language | Python (current version) | The point of the project |
| Tooling | **uv**, **ruff** (lint + format), **pyright** strict | uv ≈ `dotnet` CLI + NuGet. Strict types are the stand-in for `TreatWarningsAsErrors` and nullable reference types |
| API | **FastAPI** on **uvicorn** | ≈ ASP.NET minimal APIs: async, DI, OpenAPI built in |
| Models, settings | **Pydantic**, **pydantic-settings** | ≈ records with validation, `IOptions<T>` |
| Database | **Postgres** + **pgvector** — in **Docker** locally for now, **Neon** (free tier) when the app moves to the cloud | Neon is already used and liked: does not expire, wakes in ~1 s, vector search included. The schema is the same either way |
| Data access | **SQLAlchemy 2.0** (async) + **Alembic**, queried directly from each feature — no repository layer ([ADR 0001](adr/0001-data-access.md)) | ≈ EF Core + migrations. Worth also seeing plain SQL with `psycopg` once |
| Model API | **OpenRouter** via **httpx**, replies streamed over **SSE** | Same provider as airp; embeddings through it too |
| Token counting | **tiktoken** `o200k_base` | Same vocabulary airp counts with |
| Tests | **pytest**; HTTP faked with **httpx2**'s `MockTransport` (respx only supports httpx, and Starlette moved the project to httpx2 in step 1) | ≈ xUnit, a fake `HttpMessageHandler` |
| Web client | **SvelteKit**, built static (`adapter-static`), as a **PWA** | Close to plain HTML; light on a phone; installable without an app store |
| Terminal client | **Textual** (Python) | Screen stack, key bindings with a footer legend, command palette, themes and mouse built in — what airp's shell built by hand on Spectre.Console; async, so streamed replies fit; tested with pytest; the language the project exists to teach |
| Hosting | **Render free tier**, *when the app is ready for the cloud* (decided 2026-10-05: local first): API as a web service (sleeps; that is accepted), web client as a **static site** (does not sleep) | $0/month. The UI opens instantly and shows "waking the server…" |
| Secrets | Render environment variables; a local `.env` | Never in the repository |

**Considered and set aside, with the reason:**

- **MongoDB.** The data looks document-shaped, but what makes it work is relational: append-only
  rules, an insert-only ledger, facts with validity ranges, joins. Postgres enforces those itself.
- **Flutter.** Flutter web draws text on a canvas — heavy, and poor for long scrolling prose. And
  the app stores do not accept an NSFW roleplay app, so its mobile half would buy little.
- **Next.js.** Its strengths need a running Node server, i.e. a second backend that also sleeps.
  As a static export it is just React with extra weight. React + Vite would be the fair
  alternative if React experience ever matters more than Svelte's simplicity.
- **FastAPI + Jinja2 + htmx.** A real option (all Python, no JS framework), set aside because the
  whole app would sleep — a blank tab for 30–60 s after every quiet spell — and there is no offline.
- **Keeping airp's C# terminal client** and pointing it at the API. The most reuse, but a second
  language and toolchain in the repo, and it teaches no Python. The terminal client is a rebuild
  that carries over airp's look, keys and behaviour — not its code.
- **Importing airp's library and stories.** The owner adds the library by hand through the editor,
  as a chance to curate it, and stories start from scratch (2026-10-05).

---

## Hosting facts that shape the design

Verify each against the providers' current docs before relying on it; they have changed before.

- **Render free web services sleep** after idling and take ~30–60 s to wake. **Static sites do not
  sleep.**
- **Render's free tier has no persistent disk.** Nothing may be stored on the filesystem: no
  SQLite, no library files. Everything lives in the database (local Postgres now, Neon later).
- **Render's free Postgres expires** about a month after creation. That is why the database is Neon.
- **`onrender.com` is on the Public Suffix List**, so `app.onrender.com` and `api.onrender.com` are
  *different sites* to a browser. Cookies set by the API are third-party and increasingly blocked.
  → Authenticate with a **bearer token in the `Authorization` header**, and configure **CORS** in
  FastAPI. A custom domain later would remove the issue.
- **Neon:** use its **own project** (or at least its own branch), separate from anything else
  already there. `CREATE EXTENSION vector;` enables pgvector. Use the connection string with SSL.
- **Privacy is a deliberate trade:** airp kept the history on the owner's own machine. This keeps
  it in someone else's cloud.

### The providers' content policies

Read on 2026-10-02. A reading of the policies, not legal advice; both can change, so read them
again before the move to the cloud.

- **Render** — the [Acceptable Use Policy](https://render.com/acceptable-use) (last modified
  2025-08-22) has no ban on adult or sexual content. It forbids content that is unlawful, abusive,
  defamatory, hateful "or otherwise objectionable", and names child sexual exploitation.
- **Storing the stories in Neon does not put them outside Render's rules.** Render's
  [Terms of Service](https://render.com/terms) (2026-07-10) count what an app *displays* through
  the service as "User Content", and Render may remove User Content at its own discretion.
- **Neon** — its terms now sit under the Databricks
  [Master Cloud Services Agreement](https://www.databricks.com/legal/mcsa), whose
  [Acceptable Use Policy](https://www.databricks.com/legal/acceptable-use-policy) (2026-03-20)
  restricts illegal content and third-party rights, not the type of content. Databricks' *Free
  Edition* policy does ban pornography, but that is a different product and Neon's terms do not
  refer to it.

What follows for the design:

- **Text only, private, behind sign-in.** Every endpoint except `/health` requires the bearer
  token; nothing is public.
- **Every character in a sexual scene is an adult.** It is the law and Render's explicit rule,
  and the rule covers depictions, so it covers text.
- **"Otherwise objectionable" is the remaining risk**, because Render decides what it means. The
  stories live in Neon, so a suspended Render service would not lose them.

---

## The data model (first sketch)

The library moves from text files into tables, and several things airp enforced in code become
database rules.

```sql
characters (id, name, card TEXT, opening TEXT NULL, version INT, updated_at)
personas   (id, name, text TEXT, version INT, updated_at)
snippets   (id, name, text TEXT, version INT, updated_at)
-- names unique without regard to case: a unique index on lower(name)

library_history (id, kind, entry_id, text, opening, saved_at)        -- insert-only

settings (default_persona_id → personas)

stories  (id, name, character_id → characters ON DELETE RESTRICT,
                    persona_id   → personas   ON DELETE RESTRICT NULL,
                    created_at, deleted_at NULL)

messages (id, story_id, sequence, role, text, request_hash UNIQUE NULL,
          model, provider, prompt_tokens, completion_tokens,
          estimated_prompt_tokens, context_audit, sent_at, deleted_at NULL)

summaries  (id, story_id, from_sequence, to_sequence, text, created_at)
facts      (id, story_id, subject, text, valid_from, valid_to NULL, pinned)
embeddings (message_id, vector VECTOR(1536))                         -- HNSW index
spend      (id, story_id, kind, model, provider, cost NULL,
            prompt_tokens, cached_tokens, completion_tokens, at)    -- insert-only
asides     (id, story_id, question, answer, asked_at)               -- never enters a prompt
```

**Improvements over airp that the database gives for free:**

| airp (files, C#) | Here (Postgres) |
|---|---|
| A story stores the character's *name*, so renaming is impossible | A story stores the *id*: renaming is free |
| "Not while a story uses it" checked in code, per front end | `ON DELETE RESTRICT`: the database refuses |
| An opening belongs to a character because file names match; orphans happen | The opening is a column on the character: no orphans possible |
| One `.bak` of the last save | `library_history` keeps every saved version |
| Concurrent edits caught by hashing the file | `UPDATE … WHERE id = $1 AND version = $2`; zero rows means someone saved first |
| Append-only enforced in `SaveChanges` | A trigger rejects `DELETE` and any `UPDATE` of `messages.text`; hiding is `deleted_at` |

**Kept on purpose:** stories reference the library **live** — editing a card reaches every story
from its next turn. The default persona applies to any story that picks none. Snippets are copied
into a message when used and never read again.

**Not now:** airp's "a story's own text wins over the file". A duplicated card does the same job;
add it only if it is missed.

---

## Lessons carried over from airp

Each was measured on real stories and cost real time. Do not re-learn them.

**The prompt**

- **Layers ordered from least to most volatile** — character, persona, directives (dials), world
  facts, summaries, history, recalled memories, trackers, instruction. A provider's prefix cache
  keeps everything up to the first thing that changed; retrieval in the middle would break the
  cache every turn.
- **A budget far below the model's window** (airp: 32,000 tokens by default). Attention thins out,
  and every token is paid for on every turn.
- **When the budget is tight, the transcript gives way, oldest first** — but **the newest turn is
  always kept**, even over budget. A real story once lost the reader's own message from its prompt.
- **Recalled memories are capped at a share of the budget** (airp: 10%), not just by count: four
  long recalled turns once filled a 60,000-token prompt.
- **Count tokens with the real vocabulary**, never a characters-per-token constant: Spanish and
  English differ by ~30%.

**The memory**

- Three mechanisms, each answering a different question: **summaries** (what happened),
  **retrieval** (what was said — embeddings over *already-summarised* turns only), **facts** (what
  is true now, with `valid_from`/`valid_to`).
- **They fire only when needed**; a story that fits its budget costs no extra call.
- **Compress in batches: at least 10 messages, at most 40, never the 6 newest.** Compressing only
  the overflow ran every turn on two messages; a single call over 99 messages came back as `##`.
- **Refuse a summary too short to account for what it replaces** (a compression ratio above ~60×;
  working ones run 3–19×). If compression fails, **go over budget rather than discard**.
- **Summaries at temperature 0.3, facts at 0.2.** A creative summariser invents history the
  character then believes. Output ceilings: 1,200 tokens for a summary, 4,000 for fact extraction
  (a reasoning model thinks first).
- **Hand-written facts are pinned**: the extractor cannot retire them.
- **Name the reader by their persona, never "User"**, in anything a model reads.
- **Background calls retry once**, only for failures a retry could fix (timeouts, 408, 429, 5xx,
  a 200 with no content).
- **Every test of the memory must use a real character of realistic size.** airp's tests set a
  four-token card inline, and missed a bug that cost a real story twenty-four turns of memory.

**The data**

- **Persist the reader's turn before calling the model.** A failed call never loses what was written.
- **Idempotency by request hash, anchored on the last reply** — not on the next free position,
  which changes on retry.
- **Messages are append-only**; a reroll hides the old reply and keeps it for the audit.
- **Spend is a ledger**, one row per billed call whatever became of it. **Read the real cost from
  `usage.cost` in each response; never compute it from a price list** — prices change daily, hosts
  differ, caching discounts.
- **An out-of-character question (`/ask`) is never a turn**: stored apart, never in a prompt.
- **Audit every reply**: per-layer token breakdown, estimate against the reported figure.

**The models**

- **Criterion #1: uncensored.** Prose second, cost a distant third. A refusing summariser is a
  character that forgets.
- **Default: DeepSeek V4 Flash** on OpenRouter.
- **Send `reasoning: {enabled: false}` on replies and `/ask`.** Without it, the default came back
  empty 3 times in 5 at a 400-token ceiling, every token spent thinking.
- **Temperature depends on the model.** Roleplay finetunes wrote cleanly up to 0.9 and turned to
  token soup at 1.3; DeepSeek holds at 1.3.
- **One model for every story.** airp's choice of six models per story gave nothing back: the
  one billed as the most explicit wrote about like the default, and the larger ones cost several
  times as much for no difference a reader could name. The card, the dials and the host change
  the writing. Lustjinn built the choice in step 7 and took it out (#140); changing the default
  is one setting.
- **OpenRouter spreads a model across hosts**, and they differ: some cache prompts and some do not,
  some return empty replies or garbage. Store `provider` per reply, and allow ignoring or
  preferring hosts by slug.
- **Every instruction sent to the model must say what it is** — an out-of-character direction — and
  that the reply must be the scene itself. A bare directive gets echoed back as the reply.
- **Slash commands that are not recognised are refused, never sent.** A typo must never become a
  permanent, billed turn.

---

## Roadmap

Each step teaches one thing, and the app grows with it. Steps 1–3 already give something playable.
One GitHub milestone per step; one PR per step, one commit per issue. **custom-airp is the donor of
logic for steps 2–9**: `docs/DONOR.md` maps every step to the donor files, rules, tests and
decision records to port from.

1. **Hello, deployed.** uv project, FastAPI with one endpoint, one pytest test, ruff + pyright in
   CI, a deploy path to Render. *Teaches: layout, uv, uvicorn, how Python is served.* — Done
   2026-10-05, except the deploy itself, postponed with the move to the cloud.
2. **Stories and messages.** A Postgres with pgvector in Docker, settings, sign-in, SQLAlchemy
   models, an Alembic migration, the append-only trigger in SQL, the stories API, a dummy
   character to play and test with. *Teaches: the ORM, async sessions, transactions.*
3. **One turn against OpenRouter.** httpx, the reply streamed over SSE, the turn persisted first,
   the spend row from `usage.cost`, reroll, slash commands. *Teaches: async I/O, streaming, error
   handling.*
4. **The library.** Characters (with their opening), personas, snippets; optimistic concurrency;
   history; snippets expanded at send time. *Teaches: foreign keys, constraints.*
5. **The context builder.** Layers in order, the budget with tiktoken, the newest turn always kept,
   the audit. *Teaches: pure logic, fixtures, dataclasses — mostly tests.*
6. **The memory.** Batched summaries, pgvector retrieval, facts, background retries. *Teaches:
   background work, vector queries, larger design.*
7. **Story features.** What airp does beyond the core loop, as API features both clients use:
   `/do`, carry on, `/focus`, regenerate with a reason, a model per story with fallback (taken out
   again, #140), dials,
   meters, branching, delete-from, search, export, cost reports, editable facts, memory rebuild,
   purge, `/recap`. *Teaches: growing an API feature by feature on the foundations of 2–6.*
8. **The SvelteKit PWA.** A design system in dark and light, approved by the owner before the
   screens are built; story list, reading and writing with streamed replies, the library editor,
   a "waking the server" screen, installable on the phone.
9. **The terminal client.** Textual; airp's look, keys and behaviour, dark by design; talks to the
   same API. *Teaches: Textual, an async client of our own API, a second package in a uv
   workspace.*

**Definition of done for step 1:** `uv run pytest` passes, `ruff check` and `pyright` are clean,
and CI runs them on every pull request. (The original also required the deployed URL to answer
`GET /health`; the deploy moved to *Later* with the cloud, 2026-10-05.)

---

## Settled before step 1 (2026-10-01)

1. **Working mode: Claude writes the code.** The learning happens through **the course**: a PDF
   (source in `docs/course/`) that explains every step as it is built, mapped to .NET. Each step's
   chapter is its own issue and its own commit, in that step's PR; a step is not done until its
   chapter is.
2. **Where the repo lives:** GitHub, `argamboad/lustjinn`, private (since 2026-10-02; it began on a
   self-hosted Forgejo, now retired). `develop` is the default branch and every pull request merges
   into it; `main` is for releases only. Render deploys from this repository.
3. **The name:** **Lustjinn** — lust + djinn. `lustjinn` in code, repositories and file names. It
   replaced the working name *lustee*.
4. **Authentication: a username and a password** in environment variables (Render in production,
   `.env` locally). The PWA signs in once with them and receives a **bearer token** it keeps on the
   device — which keeps the bearer-token constraint above. The details (token format, lifetime,
   the signing secret) are decided when auth is built.
5. **Svelte 5**, latest, runes (`$state`, `$derived`) from the start — and beware that many
   examples online still use Svelte 4 syntax.
6. **The web UI is dark and light, both first-class** — designed, not default. Tokens for both
   themes, the system setting by default, a remembered switch. **The owner approves the look and
   feel** twice: the design system and the two key screens before the rest is built, and every
   screen when done (2026-10-05; this replaced "the UI is dark").

## Settled on 2026-10-05

7. **Two clients, one API.** A terminal client joins the web app, built with **Textual**; it is
   **dark by design**, like a real terminal app — one theme, no switch, no approval gate. Every
   feature is an API endpoint first; neither client reaches the database.
8. **Local first, cloud later.** The database is a Postgres with pgvector in Docker; Neon and
   Render come when the app is worth putting in the cloud. The design still respects the cloud's
   constraints (no filesystem writes, bearer-token auth, CORS), so the move is a connection string
   and a deploy hook.
9. **No imports from airp.** The owner curates the library by hand through the editor; stories
   start from scratch. A dummy character written by Claude serves as the test fixture and as
   something to play with until then.
10. **custom-airp is the donor of logic**, not of code or data. `docs/DONOR.md` is the map; every
    GitHub issue carries a *Donor* note naming its sources.
