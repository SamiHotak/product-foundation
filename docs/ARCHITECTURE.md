# Architecture

## Big picture

```
Browser ──► Next.js (port 3000) ──/api/*──► FastAPI (port 8000) ──► PostgreSQL + pgvector
                                                │
                                                ├──► Redis ◄── Celery worker (background jobs)
                                                │          ◄── Celery beat (scheduled jobs)
                                                ├──► S3 storage (phase 4B; Hetzner Object Storage in prod)
                                                └──► Email provider (Mailpit locally)
```

The browser only talks to Next.js. Next.js forwards every `/api/*` request to FastAPI
(`frontend/next.config.ts`). Same origin means no CORS setup for the app, and login cookies
(phase 2) stay first-party.

## Backend layers

```
routers/       HTTP only: parse input, call a service, return a schema
services/      business logic
repositories/  the only code that queries the database (always scoped to an organization)
models/        SQLAlchemy tables
schemas/       Pydantic request/response models (the API contract)
core/          config, logging, errors, middleware
workers/       Celery app, tasks, beat schedule
llm/           the one place for LLM calls (phase 4B)
```

Rule: no business logic in routers. Services raise `AppError` subclasses
(`app/core/errors.py`); the error handlers turn them into one JSON format:

```json
{ "error": { "code": "not_found", "message": "...", "request_id": "..." } }
```

## Cross-cutting behaviour

- **Config** comes only from environment variables (`app/core/config.py`). Production refuses to start with the dev secret key.
- **Logging** is structured (structlog). JSON in production, readable in dev. Every line carries the `request_id`. Keys like `password` and `token` are redacted.
- **Request id**: accepted from the proxy if well-formed, otherwise generated; returned in the `X-Request-ID` header and in every error.
- **Health**: `GET /api/health` (process alive) and `GET /api/health/ready` (Postgres + Redis reachable; 503 if not). Error text from failing checks never reaches the client.
- **Database**: async engine for the API, sync engine for Celery and Alembic (both psycopg 3). Schema changes only through Alembic migrations.
- **Background jobs**: see below.
- **API contract**: the OpenAPI schema is exported to `frontend/lib/api/openapi.json` and turned into
  TypeScript types (`schema.d.ts`). Every error response is typed with the standard envelope.
  Operation ids are the Python function names. CI fails if the committed files are out of date.

## Accounts, sessions and workspaces (phase 2A)

**Tables:** `users`, `organizations`, `memberships` (user + organization + role owner/admin/member),
`sessions`, `auth_tokens`. Tenant data (today: `jobs`) has an `organization_id`.

**Sessions** are server-side. The browser holds a random 256-bit token in the `session` cookie
(httpOnly, SameSite=Lax, Secure in production, 30 days, extended while used). The database stores
only its SHA-256 hash. Sign-out deletes the row; a password reset deletes all of a user's rows.
Every sign-in creates a new token (no session fixation).

**Flows** (`app/services/auth.py`):

| Flow | Notes |
| --- | --- |
| Sign up | Creates the user + "Name's workspace" (owner). Sends a confirmation link (48 h, single use). Same answer whether or not the email exists. |
| Confirm email | Uses the link, then signs in. |
| Sign in | Argon2id password check. Unconfirmed accounts get `email_not_verified` (403) and can ask for a new link. |
| Forgot / reset password | Link valid 60 min, single use. Reset signs out everywhere. |
| Google | Authorization code + PKCE + `state` cookie. Only verified Google emails. Linking to an existing *unconfirmed* account removes that account's password (stops pre-registration takeovers). |

**Brute-force protection** (Redis counters, `app/core/rate_limit.py`): 5 wrong passwords lock that
email for 15 minutes; max 20 auth requests per minute per IP; max 5 emails per address per hour.
Messages never reveal whether an email is registered.

**CSRF:** SameSite=Lax cookie + `CsrfMiddleware`: state-changing requests that carry the session
cookie must come from an allowed origin (`APP_URL`, `CORS_ORIGINS`).

**Workspaces:** each session has an active organization. `OrgCtx` (in `app/routers/deps.py`) gives
every endpoint the user + active organization; repositories filter every tenant query by
`organization.id`. Another workspace's data returns 404, never 403 (its existence is not revealed).
`tests/test_org_isolation.py` proves it with two real users; add every new tenant endpoint there.

**Emails** are queued to the worker (`send_email` task, retries while the mail server is down).
Locally they go to Mailpit; phase 4A adds a real provider.

**Frontend:** `app/(app)/layout.tsx` loads `/api/auth/me` on the server and redirects to `/login`
when signed out (no flash of the app). Forms read their values from the DOM on submit, so text
typed before the page finished loading is kept.

## Background jobs

```
UI ──POST /api/jobs/example──► JobService   (scoped to the active workspace) ──1. insert row (queued), COMMIT
                                          └─2. send Celery task (task id = job id)
Worker (JobTask base class):
  before_start  -> running, attempts + 1
  report.progress(pct, msg) from the task body
  on_retry      -> queued, "Retrying (attempt n of m)"   (TemporaryError, exponential backoff)
  on_success    -> done, progress 100, result
  on_failure    -> failed, SAFE error text (JobFailedError message, else a generic text + job id)
UI ──GET /api/jobs (or /api/jobs/{id}) every 1 s while a job is queued/running, then stops.
```

- The row is committed **before** the task is sent, so a fast worker always finds it.
- If Redis is down, sending fails in well under a second; the job is marked failed and the API returns 503.
- Celery keeps no results (`task_ignore_result`); Postgres is the single source of truth.
- Tasks are acknowledged after they finish, so a crashed worker's job runs again (`attempts` shows it).
- Polling instead of Server-Sent Events: simpler, works through every proxy, and costs one small
  request per second only while a job is active.
- Jobs belong to a workspace (`organization_id`) and need sign-in.

## Quality gates

| Where | What |
| --- | --- |
| `git commit` | pre-commit: whitespace, line endings, YAML/JSON/TOML, private keys, ruff |
| CI backend | ruff, mypy (strict), `alembic upgrade` + `alembic check` + downgrade/upgrade, pytest with real Postgres + Redis, coverage >= 80 %, OpenAPI file up to date |
| CI frontend | generated client up to date, eslint, tsc, prettier, `next build` |
| CI e2e | the full `make dev` stack in Docker + Playwright in Docker (desktop + phone) |

## Frontend

- `app/(marketing)` — public pages (phase 3B builds the full landing page)
- `app/(app)` — the logged-in app inside `AppShell` (sidebar, top bar, main sheet)
- `components/ui` — design-system primitives (button, dropdown menu, sheet, skeleton, empty state)
- `config/product.ts` — per-product identity: name, monogram, accent colour, navigation
- `lib/api` — generated types + typed client (`api`, `unwrap`, `ApiError`)
- `hooks/use-jobs.ts` — `useRecentJobs`, `useJob`: live job status by polling
- `components/jobs` — `JobProgress` (reusable job status row) and the dashboard jobs panel
- `tests/e2e` — Playwright tests (run in Docker: `make e2e`)
- Design tokens live in `app/globals.css` as CSS variables, with a dark-mode set.
- Theme (light / dark / same as device): `lib/theme.ts`, `components/theme-provider.tsx`, `app/globals.css`.
  No script runs before the first paint. "Same as device" = no class on `<html>`, CSS follows
  `prefers-color-scheme`. "Light"/"Dark" are saved in a `theme` cookie and the server renders
  `<html class="dark">`, so there is no flash. Never render a `<script>` or `<style>` tag through React (the product accent is a `style` on `<html>`): when a
  browser extension changes the page, React re-renders it on the client and logs an error.
  E2E tests cover console errors, the extension case, and the saved theme.

## Planned by phase

| Phase | Adds |
| --- | --- |
| 1B | generated typed API client, job status table + live UI, CI, pre-commit (done) |
| 2A | accounts, email verification, password reset, Google, sessions, brute-force protection, workspaces (done) |
| 2B | invites, role permissions, member management, API keys, audit log, GDPR export/delete |
| 3 | full design system, settings pages, theming, marketing site, legal pages |
| 4 | Stripe billing + usage limits, files, emails, LLM gateway, admin, demo mode |
| 5 | production deployment on Hetzner, backups, monitoring |
