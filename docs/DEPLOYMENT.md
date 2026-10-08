# Deployment

The API runs on **Render's free tier** as a native Python web service, built from this repository
on GitHub. GitHub Actions drives every deploy; nothing deploys on a push. Today there is one environment,
**staging**, from `develop`, on Render with its database on Neon. Production from `main` is tracked
in the *Later* milestone.

## How a deploy runs

GitHub → Actions → **CI** → *Run workflow* on `develop`, with **deploy = staging**. The run:

1. runs the gates (ruff, pyright, pytest) — nothing deploys unless they are green;
2. calls the Render deploy hook;
3. polls `GET /health` until the service reports this commit (`commit` comes from Render's
   `RENDER_GIT_COMMIT`), for up to 15 minutes.

The service itself is described in `render.yaml`: build `uv sync --locked --no-dev`, start uvicorn
on Render's `$PORT`, health check `/health`, automatic deploys off.

## One-time setup

### 1. Render: create the service from the blueprint

1. Render's GitHub app must be allowed to read the private repository `argamboad/lustjinn`
   (GitHub → Settings → Applications → Render → Repository access).
2. Render → **New → Blueprint** → `argamboad/lustjinn`. It reads `render.yaml` and creates
   `lustjinn-staging` on the free plan.
3. Note the service URL (`https://….onrender.com`).
4. Service → **Settings → Deploy Hook**: copy the URL. It contains a key — treat it as a password.

Creating the service runs a first build from `develop`. It will fail to start until the
environment below is set: the service has no database and no credentials yet.

### 2. Neon: the database

The free tier has no disk; the data lives in a **Neon** Postgres (17, with pgvector). Create a
project there and take its **direct** connection string, never the pooled one (the pooler does not
carry what SQLAlchemy's asyncpg driver needs). Rewrite it for the driver:

- `postgresql://` becomes `postgresql+asyncpg://`;
- the query string becomes `?ssl=require` — drop `sslmode` and `channel_binding`, asyncpg does not
  know them.

The migrations do not run on deploy; run them from the laptop, with the variable pointing at Neon
for the one command (PowerShell; the shell forgets it afterwards):

```powershell
$env:LUSTJINN_DATABASE_URL = "postgresql+asyncpg://…?ssl=require"; uv run alembic upgrade head
```

Migration 0008 creates the `vector` extension itself. The same trick seeds the dummy character and
persona for a first turn: `uv run python scripts/seed_dummy.py`. A schema change later means the
same command again, before the deploy that needs it.

### 3. Render: the API's environment

Render → `lustjinn-staging` → **Environment**. Every variable is read by `src/lustjinn/settings.py`
and documented in `.env.example`; the names are the same, there is just no `.env` in the cloud.

| Variable | Value |
|---|---|
| `LUSTJINN_DATABASE_URL` | the Neon string from step 2, in asyncpg form |
| `LUSTJINN_USERNAME`, `LUSTJINN_PASSWORD` | the one user who can sign in |
| `LUSTJINN_TOKEN_SECRET` | at least 32 characters: `uv run python -c "import secrets; print(secrets.token_urlsafe(48))"`. Changing it signs every device out |
| `LUSTJINN_OPENROUTER_API_KEY` | from https://openrouter.ai/keys; without it the app starts and every turn fails |
| `LUSTJINN_CORS_ORIGINS` | `["https://lustjinn-web-staging.onrender.com"]` — the static site, as a JSON list (see below) |

The optional ones (`LUSTJINN_MODEL`, `LUSTJINN_CONTEXT_BUDGET`, the provider lists…) keep their
defaults unless set; `.env.example` lists them all with their defaults. Two of them are about
exposure, and their defaults are the deployed ones, so leave them unset on Render:

- `LUSTJINN_DOCS` — off: `/docs`, `/redoc` and `/openapi.json` answer 404. Only `.env` turns them
  on, for development.
- `LUSTJINN_SIGN_IN_ATTEMPTS`, `…_WINDOW_MINUTES`, `…_FAILURE_DELAY_SECONDS` — five wrong
  sign-ins within fifteen minutes refuse sign-in with `429` and a `Retry-After` for the rest of the
  window, even with the right password; each wrong one waits a second. The count lives in the
  database (`sign_in_failures`), so a sleeping service does not forget it. `UV_VERSION` comes from the
blueprint. After a change, the service restarts on its own; a deploy is not needed.

### 4. GitHub: secret and variable

GitHub → `argamboad/lustjinn` → **Settings → Secrets and variables → Actions**.

| Secret | Value |
|---|---|
| `RENDER_DEPLOY_HOOK_STAGING` | the deploy hook URL from step 1 |

| Variable | Value |
|---|---|
| `STAGING_BASE_URL` | the service URL from step 1, without a trailing slash |

Without the hook secret, a deploy run ends green with a notice and deploys nothing.

## The web app: a static site

The PWA is a second service in `render.yaml`, `lustjinn-web-staging`: a **static site**, so it never
sleeps and opens instantly, and shows the lamp while the API wakes. Render builds it from `web/`
(`npm ci && npm run build`), serves `build/`, rewrites every path to `index.html` (a single-page
app), and the build writes the commit to `/version.txt` for the deploy run to check.

The site and the API have to know each other, which makes the first deploy a two-step dance:

1. **The API's URL goes into the site's build.** Render → the static site → **Environment** →
   `VITE_API_URL` = the API service's URL (`https://lustjinn-staging.onrender.com`, no trailing
   slash). It is baked in at build time, so a change needs a new build.
2. **The site's URL goes into the API's CORS list.** Render → `lustjinn-staging` → **Environment** →
   `LUSTJINN_CORS_ORIGINS` = `["https://lustjinn-web-staging.onrender.com"]`. Without it the
   browser is refused on every call; the API itself never is.

Then, in GitHub's Actions secrets and variables:

| Secret | Value |
|---|---|
| `RENDER_DEPLOY_HOOK_WEB_STAGING` | the static site's deploy hook URL |

| Variable | Value |
|---|---|
| `WEB_STAGING_BASE_URL` | the static site's URL, without a trailing slash |

A deploy run with **deploy = web-staging** (or **both**, for the API as well) fires the hook and
waits until `/version.txt` says this commit. Each deploy costs a few billed Actions minutes for the
waiting; Render's own build minutes are the static site's, which are free.

Installing it: open the site on a phone and choose *Add to Home Screen* (Safari's share sheet;
Chrome offers it). It opens full-screen under the logo, and the shell opens offline.

## When a deploy fails

- **"did not report … within 15 minutes"** — read the deploy's log in Render's dashboard; the build
  or the start command failed, or the service is still starting.
- **The service never starts** and the log ends at an import or a settings error — a variable from
  step 3 is missing or misspelt; `LUSTJINN_DATABASE_URL` in the pooled or `sslmode` form fails here.
- **Sign-in answers 429** — five wrong passwords within fifteen minutes. Wait out the time the
  message gives; the count clears itself, and a successful sign-in clears it at once.
- **The service sleeps** after ~15 minutes without requests and takes ~30–60 s to wake. That is the
  free tier, not a failure.
