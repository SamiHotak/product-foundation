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
- **Background jobs**: tasks retry temporary errors with backoff, are acknowledged only after finishing (a crashed worker's task runs again), and report progress. Phase 1B stores job status in the database for a live UI.

## Frontend

- `app/(marketing)` — public pages (phase 3B builds the full landing page)
- `app/(app)` — the logged-in app inside `AppShell` (sidebar, top bar, main sheet)
- `components/ui` — design-system primitives (button, dropdown menu, sheet, skeleton, empty state)
- `config/product.ts` — per-product identity: name, monogram, accent colour, navigation
- Design tokens live in `app/globals.css` as CSS variables, with a dark-mode set.

## Planned by phase

| Phase | Adds |
| --- | --- |
| 1B | generated typed API client, job status table + live UI, CI, pre-commit |
| 2 | users, organizations, roles, invites, API keys, audit log, GDPR export/delete |
| 3 | full design system, settings pages, theming, marketing site, legal pages |
| 4 | Stripe billing + usage limits, files, emails, LLM gateway, admin, demo mode |
| 5 | production deployment on Hetzner, backups, monitoring |
