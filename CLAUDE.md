# CLAUDE.md

> Operating manual for Claude Code on this project. Auto-loaded each session — keep it tight.

## What this project is
**lustee** is a web app for NSFW roleplay with a memory that does not forget: a Python rebuild of
the good parts of airp (`argamboad/custom-airp`, .NET 10). **The full brief is `docs/KICKOFF.md` —
read it whole before the first task of a session.** It holds the decided stack, the data-model
sketch, the lessons airp paid for, and the roadmap.

## How to work here
- **The goal is learning Python as a backend**, not shipping. The owner is an experienced
  C#/.NET developer: explain Python by **mapping it to the .NET equivalent** (ASP.NET Core, EF Core,
  xUnit, `IOptions<T>`…).
- **Prefer teaching over generating.** Scaffolding the boring parts (layout, tooling, CI) is fine;
  logic is explained, written by the owner, then reviewed — unless the agreed working mode says
  otherwise. Ask which mode when it matters.
- **One change at a time**, confirmed before moving on.
- **Do not invent and do not assume.** If a fact is missing, ask.
- **The lessons in `docs/KICKOFF.md` are binding.** Do not re-learn them; if a task seems to
  contradict one, stop and say so.
- **Never commit secrets.** They live in Render environment variables and a local `.env`
  (gitignored).

## Repository
- `origin` is **Forgejo** (`ssh://git@localhost:2222/argamboad/lustee.git`); `github` is a mirror.
  Branch from `develop`; PRs and merges happen on Forgejo.
- Branches: `main` (production), `develop` (integration).
