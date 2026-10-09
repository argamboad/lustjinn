# Stories and messages

Step 1 built an app that could say it was alive. Step 2 gives it something to keep: a database,
the tables for stories and their messages, a rule the database enforces by itself, an API over
them, and a lock on the door. Everything runs on your machine — Postgres in a Docker container,
the API under uvicorn. The cloud comes later and changes one connection string.

This is the chapter where Python's backend stack stops looking like a toy and starts looking
like what you already know. Almost every piece has a .NET twin; the interesting parts are the
few places where the twin behaves differently.

## Settings: one typed object from the environment

Before anything can connect to anything, the app needs to be told where the database is and who
may sign in. `src/lustjinn/settings.py`:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LUSTJINN_", env_file=".env", extra="ignore")

    database_url: str
    username: str
    password: SecretStr
    token_secret: SecretStr = Field(min_length=32)
    token_days: int = Field(default=30, ge=1, le=365)
    cors_origins: list[str] = []


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`BaseSettings` is a Pydantic model that fills itself in: each field is read from the environment
variable of the same name with the prefix — `LUSTJINN_DATABASE_URL`, `LUSTJINN_USERNAME` — or
from a `.env` file in the working directory, real variables winning. A field with no default is
required. Types are enforced: `token_days` must parse as an integer between 1 and 365.

- **`SecretStr`** wraps a string so that printing or logging the settings shows `**********`.
  You get the value out on purpose, with `.get_secret_value()`.
- **`@lru_cache`** on a function with no arguments turns it into "compute once, then return the
  same object": the settings are read on the first call and reused after that.
- **Failing early.** The app's *lifespan* — code FastAPI runs once at start-up and once at
  shutdown — calls `get_settings()`. A missing password stops uvicorn before it accepts a single
  request, with an error naming the field.

::: dotnet
`Settings` is the class you would bind with `services.Configure<Settings>(config)` and receive
as `IOptions<Settings>`; the environment-variable and `.env` layering is the configuration
builder; `Field(min_length=32)` is a DataAnnotation plus `ValidateOnStart()`. The lifespan is
`IHostedService.StartAsync`/`StopAsync` in one function, split by a `yield`.
:::

`.env` is gitignored. `.env.example` is committed and lists every variable; copy it and fill in
the blanks.

## A database in a container

`docker-compose.yml` describes one service: Postgres 17 with the pgvector extension available,
listening on port 5440 of this machine only, its data in a named volume.

```
docker compose up -d      # start it; the data survives restarts
docker compose down       # stop it; add -v to throw the data away
```

Port 5440 rather than the usual 5432 so it never collides with another project's Postgres.
Postgres 17 because Neon offers it: when the app moves to the cloud, the schema and every query
stay as they are.

## SQLAlchemy: the engine, the session, the models

SQLAlchemy is the ORM. Three objects carry it, and each has an EF Core counterpart — though the
unit of work is more explicit here.

### The engine and the session

```python
@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
```

- The **engine** owns the connection pool. One per process, created on first use.
- A **session** is one conversation with the database: it tracks the objects you loaded or
  added, and writes the changes when told. One per request.
- **`get_session`** is a generator: it yields a session to whoever asked, and the code after the
  `yield` — here, leaving the `async with`, which closes the session — runs when the request ends.

::: dotnet
The engine is the pooled connection factory behind `AddDbContext`. The session is the
`DbContext`: change tracking, identity map, one unit of work, scoped to a request. Two
differences will matter all through this project:

- **`flush()` and `commit()` are separate.** `flush()` sends the pending INSERTs and UPDATEs but
  leaves the transaction open; `commit()` ends it. EF's `SaveChanges()` does both.
- **There is no lazy loading in async code.** Touching `story.messages` cannot quietly run a
  query, because a query needs an `await`. The relationships are declared `lazy="raise"`, so a
  forgotten load fails loudly instead of deadlocking or lying. You load what you need, in the
  query — the discipline EF asks for with `Include`, enforced.
:::

`expire_on_commit=False` is the other async accommodation: by default SQLAlchemy forgets an
object's values at commit and reloads them on next access, which again would be a hidden query.

### The models

`src/lustjinn/models.py`, abridged:

```python
class Story(Base):
    __tablename__ = "stories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    character_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("characters.id", ondelete="RESTRICT"), index=True
    )
    persona_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("personas.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

A model is a class whose annotated attributes are columns. `Mapped[str]` is a NOT NULL text
column; `Mapped[str | None]` is nullable — the type hint *is* the nullability, checked by pyright
and enforced by Postgres. `mapped_column(...)` adds what the type cannot say: lengths, keys,
defaults, indexes.

Four tables exist after this step: `characters` and `personas` (minimal for now; the library
step fills them out), `stories`, and `messages`. The decisions worth noticing:

- **Ids are UUID version 7** (`uuid.uuid7()`, new in Python 3.14): unique like any UUID, but
  beginning with a timestamp, so they sort by creation time and index well.
- **A story points at its character by id**, with `ON DELETE RESTRICT`. airp stored the
  character's *name*, so renaming one was impossible, and "not while a story uses it" was checked
  in code. Here the database refuses the delete itself.
- **Deleting is hiding.** `deleted_at` is set and every query filters on it. The row stays.
- **A message has a `sequence`**, unique within its story, and a `request_hash` that is unique
  within its story *among rows that have one* — a **partial index**. Step 3 uses the hash to make
  a retried request harmless.
- **`model` is null when a person wrote the message.** The reader's turns, and a story's opening.
  A later step reads that null to know an opening must not be rerolled.

::: dotnet
`Mapped[...]` and `mapped_column` are the entity class and its `OnModelCreating` configuration
merged into one declaration. `ForeignKey(..., ondelete="RESTRICT")` is
`.OnDelete(DeleteBehavior.Restrict)`. The partial index is `HasIndex(...).HasFilter("...")`.
:::

## Alembic: the migrations

The models say what the schema should be. **Alembic** gets a database there, one versioned step
at a time, and records in a table (`alembic_version`) how far it has gone.

```
uv run alembic revision --autogenerate -m "what changes"   # write a migration from the models
uv run alembic upgrade head                                # apply what is not applied yet
uv run alembic downgrade -1                                # undo the last one
```

Autogenerate compares the models with a live database and writes the difference as Python:
`op.create_table(...)`, `op.create_index(...)`. The result is a draft — it is read, tidied and
committed like any code. `migrations/versions/0001_stories_and_messages.py` began that way.

`migrations/env.py` is the file Alembic runs for every command. Ours does two things: it takes
the database URL from `get_settings()`, so there is one source of truth, and it accepts a
connection handed in from outside — which is how the tests run the real migrations against their
own database.

::: dotnet
`alembic revision --autogenerate` is `dotnet ef migrations add`; `alembic upgrade head` is
`dotnet ef database update`; `alembic_version` is `__EFMigrationsHistory`. The difference: there
is no model snapshot file. Alembic compares against a real database every time, so the database
must be at the previous migration when you generate the next.
:::

One test keeps the two descriptions honest: it applies every migration to an empty database and
asks Alembic whether anything still differs from the models. A model edited without a migration
fails the build.

## A rule the database enforces: messages are append-only

A story's memory is derived from its transcript — summaries, facts, embeddings. If a message
could be edited or deleted, everything built from it would silently become a lie. airp guarded
this in `SaveChanges`. That protects against the application; it does nothing about a script, a
console session, or a second client. So here the rule lives where the data lives.

Migration `0002` is hand-written SQL, because a trigger is not something a model can express:

```sql
CREATE FUNCTION messages_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF current_setting('lustjinn.purging', true) = 'on' THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'messages are append-only: a message is hidden with deleted_at, ...'
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF NEW.text IS DISTINCT FROM OLD.text
       OR NEW.role IS DISTINCT FROM OLD.role
       OR NEW.story_id IS DISTINCT FROM OLD.story_id
       OR NEW.sequence IS DISTINCT FROM OLD.sequence THEN
        RAISE EXCEPTION 'messages are append-only: text, role, story and sequence cannot ...'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER messages_append_only
BEFORE UPDATE OR DELETE ON messages
FOR EACH ROW EXECUTE FUNCTION messages_append_only();
```

A trigger function runs for each affected row, before the change. `OLD` and `NEW` are the row
before and after; `RAISE EXCEPTION` aborts the statement. Reading it:

- **A delete is refused** — unless the transaction has announced a purge with
  `SET LOCAL lustjinn.purging = 'on'`. That is the one door, for the day a story is erased for
  good, and it closes by itself when the transaction ends.
- **What a turn said, who said it and where it sits cannot change** — purge or no purge.
- **Everything else may**: `deleted_at`, to hide a message; `request_hash`; columns later steps add.
- A second trigger refuses `TRUNCATE`, which empties a table without visiting rows and so never
  fires the first.

The error code is one of Postgres's own integrity codes, so SQLAlchemy raises `IntegrityError` —
the same exception as for a broken foreign key. To the application the trigger is one more
constraint.

::: note
`IS DISTINCT FROM` is `<>` that treats NULL as a value: `NULL <> NULL` is unknown, while
`NULL IS DISTINCT FROM NULL` is false. In a guard you want the second.
:::

## Dependency injection, FastAPI's way

Every endpoint that touches the database needs a session. It asks for one in its signature:

```python
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("")
async def list_stories(session: Session) -> list[StoryOut]:
    rows = await session.execute(_stories())
    return [_out(*row) for row in rows]
```

`Depends(get_session)` tells FastAPI: before calling this function, call `get_session` and pass
in what it yields. `Annotated[X, ...]` attaches that instruction to the type, and the alias
`Session` gives the pair a name so every endpoint can write `session: Session`.

There is no container and no registration step. A dependency is any callable; its own parameters
can be dependencies in turn; a generator dependency gets its cleanup run after the response.

::: dotnet
`Depends(get_session)` is constructor injection of a scoped service, declared at the point of
use instead of in `Program.cs`. The lifetime is per request, like `AddScoped`. What replaces
`ConfigureTestServices` is `app.dependency_overrides[get_session] = something_else` — a dictionary
from the real provider to its stand-in. The tests use exactly that.
:::

## The stories API

`src/lustjinn/stories.py` holds five endpoints under `/stories`: create, list, read one with its
messages, rename, delete. Three things in it are new.

**Pydantic models are the DTOs.** What comes in and what goes out are declared as classes, and
FastAPI validates the first and serialises the second:

```python
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class NewStory(BaseModel):
    name: Name
    character_id: uuid.UUID
    persona_id: uuid.UUID | None = None
    model: ModelName | None = None
```

A body with a blank name, or an id that is not a UUID, never reaches the function: FastAPI
answers 422 with the field and the reason.

**A router groups endpoints.** `APIRouter(prefix="/stories")` is `MapGroup("/stories")`; the app
includes it with `app.include_router(...)`.

**The list is one query.** For each story it needs the newest visible message — its time, to sort
by, and its first 200 characters, to show under the name. That is a `LATERAL` subquery: one that
runs per outer row and may refer to it. EF Core produces the same SQL from a correlated
`OrderByDescending(...).FirstOrDefault()`; here it is written out.

Creating a story does one more thing: if its character has an **opening**, the opening becomes
message 1, role `assistant`, with no model — a page a person wrote, not a reply to regenerate.

## Sign-in

The API will one day sit on a public URL with one user's private stories behind it.
`src/lustjinn/auth.py`:

1. `POST /auth/sign-in` takes the username and password and compares them with the settings.
2. If they match, it returns a **token**: a small signed document saying who it is for and when
   it expires (30 days by default).
3. Every other request carries `Authorization: Bearer <token>`. A dependency, `require_user`,
   checks the signature and the expiry before the endpoint runs.

The token is a **JWT** signed with HMAC-SHA256 using `LUSTJINN_TOKEN_SECRET`. Nothing is stored
on the server: the signature proves the token was issued here, and the expiry is inside it.
Changing the secret invalidates every token at once — that is "sign out everywhere".

The guard is attached where the router is included, not on each endpoint:

```python
app.include_router(auth.router)
# Everything below needs a valid token.
app.include_router(stories.router, dependencies=[Depends(auth.require_user)])
```

::: dotnet
This is `AddAuthentication().AddJwtBearer()` plus `MapGroup("/stories").RequireAuthorization()`,
without the middleware: the check is an ordinary dependency. `HTTPBearer` is the piece that
reads the header and puts an *Authorize* button on the `/docs` page.
:::

Details that are easy to get wrong, each pinned by a test:

- **Comparison in constant time** (`secrets.compare_digest`), and both name and password are
  checked before answering, so neither the reply nor its timing says which one was wrong.
- **The accepted algorithm is named explicitly.** A forged token whose header says "no signature
  needed" is refused because the server never asks the token how to verify it.
- **A token without an expiry is refused**, as is one issued for a different username.
- **One test covers every route**: it reads the app's own OpenAPI description and requires a 401
  from each path except `/health` and `/auth/sign-in`. An endpoint added next month is guarded,
  or that test fails.

::: warning
FastAPI's default 422 response includes the input it rejected. For a malformed sign-in that
input is the password; for a story it is the text. A test caught the first, and the app now
answers validation errors with the field and the problem only. Defaults are written for
tutorials — read what yours actually send.
:::

Two more things ride along. **CORS** — which browser origins may call the API — comes from the
settings and allows none by default; the web client's origin gets added when it exists. And every
response carries four headers saying it is private: not to be cached, indexed, or referred from.

## Testing against a real database

The trigger, the constraints and the queries are Postgres behaviour. Faking the database would
test the fake. So the tests use the real thing — and never the data you are playing with.

`tests/conftest.py` builds it from **fixtures**, each asking for the one before by naming it as a
parameter:

1. **`database_url`** (once per run) creates an empty database with a random name on the same
   server, and drops it at the end.
2. **`engine`** (once per run) applies every Alembic migration to it — the real migrations, so
   they are tested on every run.
3. **`session`** (per test) opens a transaction that is **never committed**, and rolls it back
   when the test ends. The code under test may call `commit()` freely: the session turns those
   into savepoints inside the outer transaction.
4. **`client`** (per test) is an HTTP client wired straight to the app in-process, with the app's
   `get_session` and `get_settings` overridden to hand out the test's own.

```python
async def test_deleting_a_story_hides_it_and_keeps_its_rows(
    client: httpx2.AsyncClient, session: AsyncSession
) -> None:
    story = await a_story(session)
    await session.commit()

    response = await client.delete(f"/stories/{story.id}")

    assert response.status_code == 204
    assert (await client.get(f"/stories/{story.id}")).status_code == 404
    kept = await session.get(Story, story.id, populate_existing=True)
    assert kept is not None and kept.deleted_at is not None
```

The test arranges through the session, acts through HTTP, and checks both the response and the
row — all inside one transaction that leaves nothing behind.

::: dotnet
`scope="session"` fixtures are `IClassFixture`/collection fixtures; the per-test rollback is
what Respawn or a transaction scope gives you in .NET; the in-process client is
`WebApplicationFactory.CreateClient()`. `async def` tests need a plugin, `pytest-asyncio`,
configured here to run everything on one event loop — the engine's connections belong to it.
:::

Tests that need a character use the **dummy**: "The Gilded Heron", a fictional card of about
1,850 words with an opening and a persona, under `tests/fixtures/dummy/`. airp's tests used a
four-word card inline and missed a bug that cost a real story twenty-four turns of memory; from
step 5 on, the memory tests here run on a card the size of a real one.

In CI the same Postgres image runs as a *service container* beside the job, on the same port, so
the tests' default connection string works there unchanged.

::: try
Bring it all up and use it:

```
cp .env.example .env                    # fill in a username, a password, a token secret
docker compose up -d
uv run alembic upgrade head
uv run python scripts/seed_dummy.py     # prints the dummy character's id
uv run uvicorn lustjinn.main:app --reload
```

Open `http://127.0.0.1:8000/docs`. Call `POST /auth/sign-in`, copy the `access_token`, press
**Authorize** and paste it. Then `POST /stories` with a name and the character id the seed
script printed — the response's first message is the opening.

Now try to break the rule. In another terminal:

```
docker compose exec db psql -U lustjinn -c "UPDATE messages SET text = 'rewritten'"
docker compose exec db psql -U lustjinn -c "DELETE FROM messages"
```

Both are refused, by the database, with no application running in between.
:::

## What step 2 leaves behind

- Typed settings that stop the app at start-up when something is missing.
- A local Postgres, four tables, two migrations, and a test that keeps models and migrations in step.
- Messages that cannot be rewritten or deleted, whoever asks.
- A stories API behind a bearer token, with every route's guard tested from the app's own schema.
- A test suite that runs against real Postgres and leaves no trace.

**Next — Chapter 3, One turn against OpenRouter.** The first conversation with a model: an async
HTTP client, the reply streamed to the caller as it is written, the reader's turn saved before
the model is asked, and a ledger row for what it cost.
