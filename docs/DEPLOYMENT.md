# Deployment

The API runs on **Render's free tier** as a native Python web service, built from this repository
on GitHub. GitHub Actions drives every deploy; nothing deploys on a push. Today there is one environment,
**staging**, from `develop`. Production from `main` is tracked in the *Later* milestone.

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

Creating the service runs a first build from `develop`.

### 2. GitHub: secret and variable

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
- **The service sleeps** after ~15 minutes without requests and takes ~30–60 s to wake. That is the
  free tier, not a failure.
