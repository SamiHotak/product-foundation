# Product Foundation

A reusable SaaS starter: FastAPI + Postgres + Redis + Celery backend, Next.js frontend.
Every product (AskDocs, LeadPilot, InvoiceAI Pro, CountVision) is created from this repo
with GitHub's **Use this template** button.

**Status:** phase 2A — accounts (email + Google), email verification, password reset, secure sessions, brute-force protection, workspaces with a switcher. Built on phase 1: app shell, typed API client, background jobs, CI.

## What's inside

| Part | Tech |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16 + pgvector |
| Background jobs | Celery worker + Celery beat, Redis |
| Frontend | Next.js 16 (App Router), TypeScript, Tailwind CSS 4, shadcn/ui style components |
| API client | Generated TypeScript types from the FastAPI OpenAPI schema (`openapi-typescript` + `openapi-fetch`) |
| Tests | pytest (unit + real Postgres/Redis), Playwright end-to-end in Docker |
| CI | GitHub Actions: ruff, mypy, migrations, pytest, client check, eslint, build, Playwright |
| Local services | Mailpit (catches emails). S3 file storage is added in phase 4B |

More detail: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Setup on Windows (one time)

Open **PowerShell** and run these one by one.

**1. Install the tools**

```powershell
winget install --id Git.Git -e
winget install --id Docker.DockerDesktop -e
winget install --id ezwinports.make -e
```

Optional, but recommended (for autocomplete and errors in your editor):

```powershell
winget install --id OpenJS.NodeJS.LTS -e
winget install --id Python.Python.3.12 -e
```

**2. Turn on WSL2** (Docker Desktop needs it)

```powershell
wsl --install
```

Restart the laptop when it asks.

**3. Start Docker Desktop**

- Open Docker Desktop from the Start menu and accept the terms.
- Settings → General → make sure **Use the WSL 2 based engine** is ticked.
- Wait until the bottom-left shows **Engine running**.

**4. Close and reopen PowerShell** so the new tools are found. Check:

```powershell
git --version
docker --version
make --version
```

All three must print a version.

---

## Run the project

```powershell
cd $HOME\Documents\product-foundation
make dev
```

The first run downloads images and installs packages: **5–10 minutes**. Later runs take seconds.

Then open:

| What | URL |
| --- | --- |
| App | http://localhost:3000 |
| API docs | http://localhost:8000/api/docs |
| Emails (Mailpit) | http://localhost:8025 |

The frontend waits for the backend to be healthy, so the app can take ~30 seconds after `make dev` finishes.

## Your first account

1. Open http://localhost:3000 → **Create account**.
2. Open **Mailpit** at http://localhost:8025. Every email the app sends lands there (nothing goes to real inboxes).
3. Click the confirmation link in the email. You are signed in and land in your own workspace.

Forgot a password? Use **Forgot password?** on the sign-in page; the reset email also appears in Mailpit.

## Google sign-in (optional)

The "Continue with Google" button appears only after you add your keys.

1. Go to https://console.cloud.google.com and create a project.
2. **APIs & Services → OAuth consent screen**: choose **External**, fill in the app name and your email. Add yourself under **Test users**.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID** → **Web application**.
   Under **Authorized redirect URIs** add exactly: `http://localhost:3000/api/auth/google/callback`
4. Create the file `backend\.env` (copy `backend\.env.example`) and fill in:
   ```
   GOOGLE_CLIENT_ID=...apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=...
   ```
   This file is private: it is in `.gitignore` and never goes to GitHub. Never paste these keys into a chat.
5. `make restart s=backend` — the button appears on the sign-in page.

## Everyday commands

| Command | What it does |
| --- | --- |
| `make dev` | Build and start everything |
| `make down` | Stop everything (your data is kept) |
| `make logs` | Follow all logs. One service: `make logs s=backend` |
| `make ps` | Show which services are running |
| `make test` | Backend tests, including real Postgres + Redis |
| `make lint` | ruff + mypy (backend), eslint + typecheck (frontend) |
| `make format` | Auto-format all code |
| `make api-client` | Regenerate the typed frontend API client. Run it after **any** backend route or schema change |
| `make e2e` | Browser tests (Playwright, inside Docker) against the running app |
| `make check` | Everything CI checks: lint, tests, API client, e2e. Run before `git push` |
| `make migrate` | Apply database migrations |
| `make migration name=add_users` | Create a migration after changing models |
| `make seed` | Load development data |
| `make example-job` | Run the example background job and watch its progress |
| `make shell` | Shell inside the backend container |
| `make psql` | Postgres console |
| `make clean` | Stop everything and **delete** local data |

Saving a file reloads the backend, the worker and the frontend automatically.

## Check everything before you push

With `make dev` running:

```powershell
make check
git status
```

`make check` runs lint, backend tests, regenerates the API client and runs the browser tests.
The first `make e2e` downloads the Playwright image (about 2 GB, once).
If `git status` then shows changed files in `frontend/lib/api`, commit them — CI fails if the
committed API client does not match the backend.

Browser test report: open `frontend/playwright-report/index.html`.

## Pre-commit hooks (one time, optional but recommended)

They check your files on every `git commit` (whitespace, line endings, YAML/JSON, private keys,
Python lint and format). They need Python on Windows (see step 1).

```powershell
cd $HOME\Documents\product-foundation
py -3.12 -m pip install pre-commit==4.6.2
py -3.12 -m pre_commit install
py -3.12 -m pre_commit run --all-files
```

If a hook **fixes** a file, the commit stops. Run `git add -A` and commit again.
CI runs the same hooks, so nothing is lost if you skip this.

## The typed API client

The frontend never writes API types by hand. The flow:

1. You change a backend route or schema (`backend/app/schemas/...`).
2. `make api-client` writes `frontend/lib/api/openapi.json` and generates `frontend/lib/api/schema.d.ts`.
3. TypeScript now knows every path, parameter and response:

```ts
import { api, unwrap } from "@/lib/api";

const job = await unwrap(api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } }));
```

`unwrap` returns the data or throws an `ApiError` with a message you can show to the user.

## Background jobs

Long work (imports, AI calls, reports) runs in the Celery worker, never inside a request.
Every job has a row in the `jobs` table with status, progress %, message and result,
so the UI can show live progress. Try it: **Dashboard → Run example job**.

To add a job to a product:

1. Write a task in `backend/app/workers/tasks.py` with `base=JobTask` and a `job_id` argument.
   Call `make_reporter(job_id).progress(40, "Reading page 4 of 10")` while it works.
   Raise `JobFailedError("message for the user")` for failures the user should read.
2. Register it in `backend/app/workers/registry.py`.
3. Start it from a service with `JobService.enqueue("your-kind", params, organization_id=..., created_by_id=...)`.
4. In the UI, follow it with `useJob(jobId)` and show `<JobProgress job={job} />`.

Temporary errors (`TemporaryError`) are retried with backoff (up to 3 times).
Other errors show a safe message to the user; the full error is in `make logs s=worker`.

Jobs belong to the active workspace: start them with
`JobService.enqueue(kind, params, organization_id=ctx.organization.id, created_by_id=ctx.user.id)`.

## Change the product name and colour

Edit `frontend/config/product.ts` (name, tagline, monogram, accent colours, menu items).

---

## Troubleshooting

**`make` is not recognized** — close and reopen PowerShell after installing. Still broken? Run `winget install --id ezwinports.make -e` again.

**`Cannot connect to the Docker daemon`** — Docker Desktop is not running. Open it and wait for **Engine running**.

**`port is already allocated`** — another program uses that port (often a local Postgres on 5432). Stop that program, or run `make down` and try again.

**The app shows "API not available"** — run `make logs s=backend` and read the last error.

**Changes to frontend files don't show** — run `make restart s=frontend`. Hot reload from a Windows folder into Docker uses polling and is sometimes slow.

**`make e2e` fails** — open `frontend/playwright-report/index.html`: it shows a screenshot and a
step-by-step trace of the failing test. Check that `make dev` is running and the app opens.

**CI fails at "OpenAPI schema is up to date" or "Typed API client is up to date"** — run
`make api-client`, then commit the changed files in `frontend/lib/api`.

**CI fails at "Pre-commit hooks"** — run `py -3.12 -m pre_commit run --all-files`, then commit the fixes.

**"Too many requests" while testing** — the brute-force protection. Wait a minute. Locally the limit is 300 auth requests per minute per IP (production: 20), and 5 wrong passwords lock that email for 15 minutes.

**The confirmation email doesn't arrive** — open http://localhost:8025. Still nothing? `make logs s=worker` (the worker sends emails).

**Something is badly broken** — `make clean` then `make dev` (this deletes your local database).

## Tests without Docker (optional)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest
```

Unit tests need no database. Integration tests only run through `make test`. They use a
separate database (`app_test`), so running tests never deletes your local accounts.
