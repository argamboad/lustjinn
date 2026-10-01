# Orientation

You already know how to build a backend. You know what a request pipeline is, what dependency
injection buys you, why migrations exist, how `async`/`await` frees a thread. None of that changes.
What changes is the vocabulary, the tooling, and a handful of assumptions so deep in .NET that you
no longer notice them — and those are the ones that bite.

This course follows **Lustjinn** as it is built: a web app for roleplay with a memory that does not
forget, the Python successor to airp. Each chapter is one step of the roadmap. Claude writes the
code; the chapter explains it — what each new piece is, why it is there, and what it would be in
.NET. When a chapter and the code disagree, the chapter is out of date: that is a bug.

## How to read this course

Every chapter has the same shape: what we are building in this step, the code that was written,
the concepts it introduced, and what changed in the repository. Four kinds of box recur:

::: dotnet
Maps a Python idea onto the .NET one you already know — and says where the analogy breaks.
:::

::: note
Background that is useful but not needed to follow the step.
:::

::: warning
A trap. Usually one that would compile — or rather, *run* — without complaint.
:::

::: try
A small exercise. Optional, but the fastest way to make a concept stick.
:::

## The map

Most of the Python toolchain has a direct counterpart in what you use every day. Keep this table
nearby; later chapters assume it.

| You know (.NET) | Lustjinn uses (Python) | What it is |
|---|---|---|
| `dotnet` CLI | **uv** | Creates projects, installs packages, runs things |
| nuget.org | **PyPI** | The public package registry |
| `.csproj` | **`pyproject.toml`** | The project file: name, dependencies, tool settings |
| `packages.lock.json` | **`uv.lock`** | Exact resolved versions, committed |
| `global.json` | **`.python-version`** | Pins the runtime version |
| Roslyn analyzers, `dotnet format` | **ruff** | Linter and formatter in one |
| The compiler + nullable reference types | **pyright** (strict) | The type checker |
| xUnit | **pytest** | Tests |
| NSubstitute, a fake `HttpMessageHandler` | **respx** | Fakes HTTP calls in tests |
| Kestrel | **uvicorn** | The web server that runs the app |
| ASP.NET Core minimal APIs | **FastAPI** | Routing, model binding, DI, OpenAPI |
| `record` + DataAnnotations | **Pydantic** models | Typed data with validation |
| `IOptions<T>` | **pydantic-settings** | Typed configuration from the environment |
| EF Core | **SQLAlchemy 2.0** | ORM and query builder |
| EF Core migrations | **Alembic** | Schema migrations |
| `HttpClient` | **httpx** | HTTP client, sync and async |
| `Task`, `async`/`await` | **asyncio** coroutines | Asynchronous code |

The table is a starting point, not a promise. The rest of this chapter covers the four places
where the mapping breaks hardest.

## Break 1 — Types are checked, but not enforced

In C#, a type is a contract the compiler enforces and the runtime relies on. In Python, a type
hint is an *annotation*: the interpreter stores it and otherwise ignores it.

```python
def greet(name: str) -> str:
    return "Hello, " + name

greet(42)   # Runs. Fails only inside, at the "+", with a TypeError.
```

Nothing stops that call at run time. What stops it is **pyright**, run before the code ships —
exactly the role the C# compiler plays, except that it is a separate tool and you could skip it.
Lustjinn runs pyright in **strict** mode, in CI, on every push: that is our `TreatWarningsAsErrors`.

::: dotnet
`str | None` is Python's `string?`. With nullable reference types on, C# warns when you
dereference something that might be null; pyright strict does the same for `None`. The difference
is that C#'s `null` checks are warnings you opted into, while in strict pyright they are errors
from the start.
:::

::: note
Some libraries *do* read type hints at run time, on purpose. **Pydantic** and **FastAPI** are the
two you will meet first: a parameter declared `limit: int` makes FastAPI parse and validate the
query string as an integer and return a 422 if it is not. That is model binding, driven by the
same annotations pyright checks.
:::

## Break 2 — There is no build step

`dotnet build` turns your project into an assembly; `dotnet run` runs the assembly. Python has no
equivalent step you run yourself. The interpreter (**CPython**, the standard one) compiles each
file to bytecode the first time it is imported, caches it in a `__pycache__` folder, and executes
it. A syntax error surfaces when the file is loaded; a typo in a name surfaces only when that line
runs.

That is why the tooling matters more than in .NET: **ruff** and **pyright** are the build. If they
are clean and the tests pass, the code is as checked as it will get before it runs.

## Break 3 — Every project gets its own interpreter environment

NuGet keeps packages in a global cache, and each project references the versions it wants; two
projects can use different versions of the same package without noticing each other.

Python installs packages *into an interpreter*. Install a package into the system Python and every
project on the machine sees that version. The answer is a **virtual environment**: a folder
(`.venv`) holding a private copy of the interpreter's package directory, one per project.

**uv** manages all of it. It downloads the Python version the project pins, creates `.venv`,
installs exactly what `uv.lock` says, and runs commands inside that environment:

```
uv sync              # make .venv match uv.lock           ≈ dotnet restore
uv add httpx         # add a dependency, update the lock  ≈ dotnet add package
uv run pytest        # run a command inside .venv         ≈ dotnet test
uv python install    # fetch the pinned Python version    ≈ installing an SDK
```

::: warning
Your Windows machine has an older system Python (3.9) on the `PATH`. Lustjinn never uses it: uv
fetches the version `.python-version` asks for and keeps it separate. If a command ever behaves as
if it were on 3.9, it was run with `python` instead of `uv run python`.
:::

## Break 4 — Async runs on one thread

In ASP.NET Core, each request runs on a thread-pool thread. If a handler blocks — a synchronous
database call, a `Thread.Sleep` — it wastes that one thread, and the pool covers for it.

Python's `asyncio` runs every coroutine on **a single thread**, inside an **event loop**. An
`await` hands control back to the loop so another request can make progress. A call that blocks
without awaiting does not waste one thread; it freezes *every* request the server is handling
until it returns.

```python
async def handler():
    time.sleep(2)            # Blocks the event loop: the whole server stops for 2 s.
    await asyncio.sleep(2)   # Yields to the loop: other requests keep running.
```

This is why Lustjinn uses the async versions of everything that waits: **httpx**'s
`AsyncClient`, SQLAlchemy's async engine, an async Postgres driver.

::: dotnet
`async def` ≈ an `async Task` method, and `await` means the same thing. The difference is what
happens *between* awaits: in .NET, other work runs on other threads; in Python, other work runs
only when you await. There is no `ConfigureAwait`, and no `SynchronizationContext` to think about.
:::

::: note
FastAPI hides one sharp edge for you. An endpoint declared with plain `def` (not `async def`) is
run on a separate thread pool, so blocking inside it is safe. An endpoint declared `async def` runs
on the event loop and must never block.
:::

## Smaller differences you will meet soon

- **Files are modules; folders are packages.** There is no `namespace` keyword and no project
  reference: `from lustjinn.stories import Story` imports by path from the package folder.
- **Naming:** `snake_case` for functions, variables and modules; `PascalCase` for classes;
  `UPPER_CASE` for constants. The leading underscore (`_helper`) means "private by convention" —
  nothing enforces it.
- **`self` is explicit.** A method's first parameter is the instance, written out. The constructor
  is `__init__`.
- **Indentation is syntax.** Blocks have no braces; the indentation *is* the block. ruff's
  formatter keeps it consistent.
- **`None`, `True`, `False`** are capitalised.

## What is already on your machine

The setup for this course and for step 1 is installed:

- **uv** — the Python toolchain. It will fetch the current Python on first use.
- **pandoc** and **Typst** — they turn the Markdown chapters of this course into this PDF.

The course lives in the repository under `docs/course/`. To rebuild it:

```
./docs/course/build.ps1          # the dark edition
./docs/course/build.ps1 -Light   # a light edition, for printing
```

::: try
Run `uv --version` and `uv python list`. The second command lists the Python versions uv can
install, and any it already has. Next chapter, one of them becomes Lustjinn's.
:::

## What is next

**Chapter 1 — Hello, deployed.** A uv project, FastAPI with one endpoint, one pytest test, ruff and
pyright in CI, and the whole thing deployed to Render — so that `GET /health` answers from the
internet. It teaches the project layout, uv in practice, and how a Python web app is actually
served.
