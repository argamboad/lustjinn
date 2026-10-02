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

## When a deploy fails

- **"did not report … within 15 minutes"** — read the deploy's log in Render's dashboard; the build
  or the start command failed, or the service is still starting.
- **The service sleeps** after ~15 minutes without requests and takes ~30–60 s to wake. That is the
  free tier, not a failure.
