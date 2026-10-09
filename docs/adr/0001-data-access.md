# ADR 0001 — Data access stays direct: no repository layer until there is more than one user

**Status**: accepted · 2026-10-09 (#134)

## Context

Each feature module queries the database itself: a route takes `session: Session` and writes
its SQLAlchemy `select(...)` where it needs it, and the few queries several features share are
plain functions in the module of their noun — `stories.visible_story`, `stories.playable_story`,
`library.persona_of`, `dials.of_story`. There is no repository and no service layer between the
routes and the session.

A reader coming from ASP.NET expects one: an `IStoryRepository` per aggregate, a service per
use case, the `DbContext` hidden behind both. The question came up in the SOLID and DRY review
of 2026-10-08 and will come up again, so the answer is written here.

## Decision

Keep data access direct. A repository layer is added only when one of the conditions below
becomes true, not before.

Why direct is the better trade today:

- **One user, one database.** The app has a single sign-in and one Postgres. Nothing varies
  behind a repository's interface, so the interface would be a second name for the session.
- **The tests use real Postgres.** Every test runs against a throwaway database on the local
  Postgres (`tests/conftest.py`), with the real constraints and the append-only trigger.
  The usual reason for a repository — swapping in an in-memory fake so the logic can be tested
  without a database — does not apply: a fake would test less than what runs now.
- **The seams already exist where something does vary.** FastAPI's `Depends` swaps the session,
  the settings and the model client per test through `app.dependency_overrides` (see
  `deps.py`). That is the test seam a repository would have provided.
- **The vertical slice reads better.** A feature's query sits next to the rule it serves, and
  SQLAlchemy 2.0's typed `select` is already the abstraction over SQL. A layer that forwarded
  every call would add a file per feature and no behaviour.

## What would change it

- **More than one user.** Every query would then need to be scoped to its owner, and a scope
  that each query must remember is the bug a repository (or a scoped session, or Postgres row-level
  security) exists to prevent. That is the first moment the layer earns its place.
- **A second backend.** A store other than Postgres for some of the data — files, a cache that
  answers instead of the database, a service — would put something real behind an interface.
- **Shared queries outgrowing their modules.** If the helpers listed above multiply and start to
  need each other, they may want a module of their own; that is a refactor of placement, still
  not a layer.

## Consequences

- New features write their queries in their own module and reach for the shared helpers rather
  than copying them (#133 moved the ones `turns.py` kept private to their nouns).
- Tests keep running against Postgres; the suite's cost is a few minutes, and it is the price
  of testing what ships.
- This decision is revisited the day a second user is on the roadmap, before that work starts.
