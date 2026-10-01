# Hello, deployed

The goal of step 1 is the smallest thing that is real: a Python web app with one endpoint, one
test, the quality gates, and a public URL that answers. Nothing about roleplay yet. Everything
later grows out of this skeleton, so it is worth understanding every file in it.

The step lands in three pieces, and this chapter grows with them:

1. **The project** — uv, FastAPI, one endpoint, one test, ruff and pyright. *(This edition.)*
2. **CI** — the gates running on Forgejo on every push. *(Coming with issue #4.)*
3. **The deploy** — Render serving the app from the GitHub mirror. *(Coming with issue #5.)*

## What uv created

One command started the project:

```
uv init --package --name lustjinn --python 3.14
```

and two more added the libraries:

```
uv add fastapi "uvicorn[standard]"
uv add --dev pytest httpx2 ruff pyright
```

The result, ignoring the docs:

```
.python-version          3.14 — which Python this project runs on
pyproject.toml           the project file
uv.lock                  every package, pinned to an exact version and hash
.venv/                   the project's private environment (gitignored)
src/lustjinn/
    __init__.py          makes the folder a package
    main.py              the FastAPI app
tests/
    test_health.py       the one test
```

Python 3.14 is pinned because it is the newest stable release: 3.15 exists, but only as a release
candidate. uv downloaded 3.14.7 on its own, without touching the Python 3.9 already installed on
the machine.

### Why the code lives under `src/`

The package is `src/lustjinn/`, not `lustjinn/` at the root. With the code at the root, `import
lustjinn` would work in tests simply because the current folder happens to be on the import path —
and a test could pass against files that would never be part of the installed app. Under `src/`,
the only way to import `lustjinn` is to install it, which uv does: `uv sync` installs the project
into `.venv` in *editable* mode, meaning the environment points at `src/` instead of copying it, so
edits are live.

::: dotnet
This is the test project's `<ProjectReference>`. A test project in .NET cannot see the app's
source files, only the assembly the reference builds. The `src/` layout gives Python the same
discipline: tests see the package as installed, the way the server will.
:::

## The project file

`pyproject.toml` is the `.csproj`. It is TOML, a format of `[tables]` and `key = value` lines.

```toml
[project]
name = "lustjinn"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = [
    "fastapi>=0.142.2",
    "uvicorn[standard]>=0.54.0",
]

[dependency-groups]
dev = [
    "httpx2>=2.13.1",
    "pyright>=1.1.414",
    "pytest>=9.1.1",
    "ruff>=0.16.10",
]
```

- **`[project]`** is the standard part every Python tool understands: name, version, the Python it
  needs, and the packages the app needs at run time.
- **`uvicorn[standard]`** — the brackets name an *extra*: optional dependencies a package offers.
  `standard` adds uvicorn's faster event loop and HTTP parser, and file watching for `--reload`.
- **`[dependency-groups]`** holds what development needs but production does not: the test runner
  and the gates. A production install leaves them out.
- **`[build-system]`** says how to turn the project into an installable package (`uv_build`).
- **`[tool.…]`** tables configure each tool — `[tool.ruff]`, `[tool.pyright]`, `[tool.pytest…]` —
  all in the one file.

::: dotnet
`"fastapi>=0.142.2"` reads like NuGet's `Version="0.142.2"`, and both mean *at least* that
version. The difference is which version gets picked: NuGet resolves the **lowest** version that
satisfies every constraint, uv the **highest**. Either way, the lock file is what makes the build
repeatable — `uv.lock` plays the role of `packages.lock.json`, and it is committed.
:::

## The app

The whole application, `src/lustjinn/main.py`:

```python
"""The FastAPI application: the object uvicorn serves."""

from fastapi import FastAPI

app = FastAPI(title="Lustjinn")


@app.get("/health")
async def health() -> dict[str, str]:
    """Answers while the process is up. Render and the PWA's waking screen poll it."""
    return {"status": "ok"}
```

Line by line:

- The string at the top of a file, function or class is a **docstring**: documentation the
  language keeps (`help()` shows it). It plays the part of an XML `<summary>` comment.
- `from fastapi import FastAPI` imports one name from a package — a `using` that names exactly what
  it brings in.
- `app = FastAPI(...)` creates the application at module level. When Python imports this file, the
  line runs, and `app` exists from then on.
- `@app.get("/health")` is a **decorator**. Python calls `app.get("/health")`, which returns a
  function; that function receives `health`, registers it as the handler for `GET /health`, and
  hands it back unchanged. The `@` line is shorthand for exactly that.
- `async def health() -> dict[str, str]` declares a coroutine that returns a dictionary of strings.
  FastAPI reads the return annotation: it documents the response in the OpenAPI schema and
  validates what the function returns.
- `return {"status": "ok"}` — FastAPI serialises the dictionary to JSON.

::: dotnet
Put side by side with a minimal API, there is almost nothing to translate:

```csharp
var app = WebApplication.CreateBuilder(args).Build();
app.MapGet("/health", () => new Dictionary<string, string> { ["status"] = "ok" });
app.Run();
```

`app.MapGet(...)` becomes the decorator, and `Dictionary<string, string>` becomes
`dict[str, str]`. What has no counterpart is `app.Run()` — see the next section.
:::

## How Python is served

A .NET app is an executable: `Program.cs` builds the app and `app.Run()` starts Kestrel inside the
same process. A Python web app is not run; it is **imported by a server**. The server here is
**uvicorn**:

```
uv run uvicorn lustjinn.main:app --reload
```

`lustjinn.main:app` means *import the module `lustjinn.main` and serve the object called `app` in
it*. uvicorn owns the process, the socket and the event loop; FastAPI only answers requests handed
to it. `--reload` restarts the server when a file changes — for development only.

The contract between the two is **ASGI** (Asynchronous Server Gateway Interface): a standard
signature every async Python server can call and every async framework implements. That is why
FastAPI could run on another ASGI server without changing a line.

::: dotnet
uvicorn is Kestrel, and ASGI is the boundary between Kestrel and the ASP.NET Core pipeline — except
that in Python the boundary is a public standard, so servers and frameworks mix and match.
:::

With the server running, FastAPI also serves its own documentation: **`/docs`** is an interactive
Swagger UI and **`/openapi.json`** the schema, both generated from the code — no Swashbuckle to add.

## The test

`tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from lustjinn.main import app

client = TestClient(app)


def test_health_answers_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- **pytest finds tests by name**: files called `test_*.py`, functions called `test_*`. No
  attribute, no test class needed.
- **Plain `assert`.** pytest rewrites assert statements when it loads a test file, so a failure
  shows both sides of the comparison — no `Assert.Equal` family to learn.
- **`TestClient`** runs the app in-process and speaks to it over ASGI directly: no server, no port,
  no network.

::: dotnet
`TestClient(app)` is `WebApplicationFactory<Program>` plus `CreateClient()`, in one line.
:::

::: warning
When this test was first written, the dev dependency was `httpx`, as countless tutorials say. The
test passed — with a deprecation warning, because Starlette (the toolkit under FastAPI) now wants
its successor, **`httpx2`**. pyright went further and failed: with `httpx2` missing, it could not
know the types of `client.get`, `response.status_code` or `response.json`, and strict mode refuses
unknown types. Two lessons in one. Tutorials age fast in Python — check what the library itself
asks for. And strict typing earns its keep on day one: it turned a quiet warning into an error.
:::

## The gates

Four commands decide whether a change is acceptable. All four are clean on this commit:

```
uv run pytest               # the tests
uv run ruff check           # lint
uv run ruff format --check  # formatting, without rewriting
uv run pyright              # types, strict
```

**ruff** is configured in `pyproject.toml` with a deliberate set of rule families. Most are style
and likely-bug checks. One deserves a mention: **`ASYNC`** flags blocking calls made inside
`async def` functions — the event-loop freeze from chapter 0, caught before it runs.

**pyright** runs in `strict` mode over `src` and `tests`. Strict means every value must have a type
pyright can know; an unknown type is an error, not a shrug.

::: try
Start the server with `uv run uvicorn lustjinn.main:app --reload` and open
`http://127.0.0.1:8000/docs`. Call `/health` from the Swagger page.

Then, in `main.py`, change the return to `{"status": 1}` and run `uv run pyright`. The annotation
says `dict[str, str]`; pyright says no. Change it back.
:::

## Still to come in this chapter

- **CI on Forgejo** — the four gates, run on every push (issue #4).
- **The deploy** — Render serving the app, and `GET /health` answering from the internet (issue #5).
