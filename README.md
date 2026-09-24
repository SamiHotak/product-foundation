# Product Foundation

A reusable SaaS starter: FastAPI + Postgres + Redis + Celery backend, Next.js frontend.
Every product (AskDocs, LeadPilot, InvoiceAI Pro, CountVision) is created from this repo
with GitHub's **Use this template** button.

**Status:** phase 1A — skeleton, local development, logging, errors, health checks, background jobs, app shell.

## What's inside

| Part | Tech |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16 + pgvector |
| Background jobs | Celery worker + Celery beat, Redis |
| Frontend | Next.js 16 (App Router), TypeScript, Tailwind CSS 4, shadcn/ui style components |
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
| `make migrate` | Apply database migrations |
| `make migration name=add_users` | Create a migration after changing models |
| `make seed` | Load development data |
| `make example-job` | Run the example background job and watch its progress |
| `make shell` | Shell inside the backend container |
| `make psql` | Postgres console |
| `make clean` | Stop everything and **delete** local data |

Saving a file reloads the backend, the worker and the frontend automatically.

## Change the product name and colour

Edit `frontend/config/product.ts` (name, tagline, monogram, accent colours, menu items).

---

## Troubleshooting

**`make` is not recognized** — close and reopen PowerShell after installing. Still broken? Run `winget install --id ezwinports.make -e` again.

**`Cannot connect to the Docker daemon`** — Docker Desktop is not running. Open it and wait for **Engine running**.

**`port is already allocated`** — another program uses that port (often a local Postgres on 5432). Stop that program, or run `make down` and try again.

**The app shows "API not available"** — run `make logs s=backend` and read the last error.

**Changes to frontend files don't show** — run `make restart s=frontend`. Hot reload from a Windows folder into Docker uses polling and is sometimes slow.

**Something is badly broken** — `make clean` then `make dev` (this deletes your local database).

## Tests without Docker (optional)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest
```

Unit tests need no database. Integration tests only run through `make test`.
