# Deployment (phase 5A)

How the product runs in production and how to operate it. The click-by-click first setup is in
[deploy/server-setup.md](../deploy/server-setup.md). This page explains the *why* and the day-to-day.

## Contents

- [Architecture](#architecture)
- [How a deploy works](#how-a-deploy-works)
- [Rollback](#rollback)
- [Migrations: the expand/contract rule](#migrations)
- [Backups and restore](#backups-and-restore)
- [Security headers and the CSP](#security-headers)
- [Sentry (error reports)](#sentry)
- [Logs](#logs)
- [Known limits](#known-limits)

## Architecture

One Hetzner server (Germany), one Docker Compose stack (`deploy/docker-compose.yml`):

```
Internet -> Caddy (80/443, HTTPS, headers, compression)
              /api/*  -> backend  (FastAPI, uvicorn, 2 workers)
              others  -> frontend (Next.js standalone)
            worker + beat (Celery)  ->  Redis, Postgres, S3
            Postgres 16 (pgvector)  and  Redis (password, no eviction)
```

- Only Caddy publishes ports. Postgres and Redis are not reachable from outside.
- Images are built by GitHub Actions and stored in GitHub Container Registry (`ghcr.io`), tagged `sha-<7 chars of the commit>`.
- Files and backups live in two separate Hetzner Object Storage buckets.

## How a deploy works

`.github/workflows/deploy.yml` runs after CI is **green** on `main` (or by hand).

1. Build the backend and frontend images and push them.
2. Copy the deploy files to `/opt/app` on the server (SSH, pinned server key).
3. On the server `./deploy.sh deploy sha-xxxxxxx`:
   pull images -> backup the database -> run migrations (old version still serves) ->
   start new containers next to the old ones -> when healthy, stop the old ones.
4. GitHub checks `https://<domain>/api/health/ready` from outside. If it fails, `./deploy.sh rollback` runs.

Visitors normally notice nothing. Caddy retries for a few seconds while containers switch (`lb_try_duration`).
It is "almost zero downtime", not a guarantee: a request that runs during the switch can fail once.

Nothing deploys until the repository variable `DEPLOY_HOST` is set. A deploy of an older commit is skipped
when a newer commit is already on `main` (so a slow CI run can never put old code on the server).
The SSH key and known-hosts line are **environment** secrets of `production`, and that environment may only
be used by `main`.

## Rollback

- Automatic: unhealthy new version -> previous version is started again.
- By hand from GitHub: Actions > Deploy > Run workflow > `tag` = an older `sha-xxxxxxx`. No build.
- By hand on the server: `cd /opt/app && ./deploy.sh rollback`.

Server images older than two weeks are deleted, so tags older than that need a rebuild (run the workflow from that commit).

When you deploy an older tag and the database is already newer than that version (because a later release
had a migration), `deploy.sh` notices that the old image does not know the database revision and **skips**
the migration step. That is safe only if you followed the expand/contract rule below.

<a id="migrations"></a>
## Migrations: the expand/contract rule

A rollback **does not undo migrations**. So during a deploy the **old code must work with the new database**.
Write every migration in two steps, in two separate deploys:

| Want to | Deploy 1 (expand) | Deploy 2 (contract) |
| --- | --- | --- |
| Add a column | add it as nullable / with default; code starts using it | (later) make it NOT NULL if needed |
| Rename a column | add the new column, write to both, backfill | read only new; drop the old one in a later deploy |
| Drop a column/table | stop using it in code | drop it in the next deploy |
| Change a type | add a new column, copy | switch code, then drop the old one |

Never: drop or rename something the currently running version still uses. Never a long lock on a big table
(add indexes with `CREATE INDEX CONCURRENTLY`).

## Backups and restore

- Backup settings live in `/opt/app/.env.backup` (passphrase, backup bucket keys, ping URL), **not** in `.env`.
  The app containers never read that file, so a hacked app cannot open or delete the backups.
- `backup.sh` runs nightly (cron, 02:30) and before every deploy.
  `pg_dump -Fc` -> AES-256 (openssl, `BACKUP_PASSPHRASE`) -> separate bucket. Nothing stays on the server disk.
- Backups older than 14 days are deleted; the newest 3 are always kept.
- `HEALTHCHECK_URL` (Healthchecks.io) is pinged after each good backup; a missing ping emails you.
- The encryption (AES-256-CBC with a key made from the passphrase) keeps the content secret. It does not
  detect tampering by someone who can write to the bucket. Protect the bucket keys (and turn on bucket
  versioning / object lock if your storage offers it).
- **Keep `BACKUP_PASSPHRASE` in your password manager.** Without it the backups cannot be opened.
- Uploaded files are in the files bucket and are **not** part of the database backup. Turn on bucket
  versioning or a copy job if you cannot lose them (not built in).

Test a restore (safe, uses a scratch database): `./restore-test.sh` (`--list` shows the backups).

### Restore into the real database

Only in an emergency. This **replaces all current data** with the backup. The steps are ordered so that
nothing is deleted before the backup is proven to work.

```bash
cd /opt/app
./restore-test.sh --list                       # pick a name, e.g. db-2026-...enc
./restore-test.sh <name>                       # 1. proves: download, passphrase and restore all work
./backup.sh before-restore                     # 2. a fresh backup of what is there now
./deploy.sh compose stop frontend backend worker beat
./deploy.sh compose exec -T postgres psql -U app -d postgres \
  -c "DROP DATABASE app WITH (FORCE)" -c "CREATE DATABASE app"
./restore-test.sh --stdout <name> \
  | ./deploy.sh compose exec -T postgres pg_restore -U app -d app --no-owner --exit-on-error
./deploy.sh deploy "$(cat .deployed_tag)"      # start everything again
```

If step 1 or 2 fails, stop there: nothing has been changed. Practise this once on a test server before you need it.

<a id="security-headers"></a>
## Security headers and the CSP

Caddy sets HSTS (180 days), `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`,
`frame-ancestors 'none'` and a Content-Security-Policy.

The CSP allows `'unsafe-inline'` for scripts and styles because Next.js writes small inline scripts into
every page. A **nonce-based** CSP would remove that, but it makes every page render on each request
(no static pages, slower). It is a possible later step; it is a trade-off, not an oversight.
Only `'self'` and your own S3 endpoint (`S3_ORIGIN`, for uploads) are allowed as other sources. No third-party scripts.

## Sentry

- Backend (`SENTRY_DSN` in `.env`) and website (`NEXT_PUBLIC_SENTRY_DSN` GitHub variable, baked in at build).
  Use a Sentry project in the **EU region**.
- What is sent: error type, stack trace, release. What is removed before sending: request bodies, cookies,
  headers, query strings, user data, IP addresses. Performance tracing is off by default (`SENTRY_TRACES_SAMPLE_RATE=0`).
- Website errors go through `/monitoring` on your own domain (so ad blockers do not hide them).
  That path is Sentry's standard tunnel: it forwards to Sentry for whatever project id is in the request.
  Consequence: someone could push junk events through your server to Sentry. There is no extra rate limit on it here.
  Set a rate limit / spam filter in Sentry, and know that it exists.
- The privacy policy, DPA and processor list say you use Sentry (EU). If you do not use it, remove those parts (`docs/LEGAL_TEMPLATES.md`).

## Logs

`docker compose logs` per service; Docker keeps 3 files x 10 MB per service. That is **size-based**:
on a busy site it may be only hours, on a quiet one weeks. Tell the truth about it in the privacy policy placeholder.
`./deploy.sh logs backend` follows one service.

## Known limits

- IPv6 is not used (no `AAAA` records): with Docker's default settings all IPv6 visitors would look like one
  address to the app. Test it on your server before you enable it.
- `postgres`, `redis` and `caddy` images use floating tags but are only pulled when missing. Update them on
  purpose: `./deploy.sh compose pull postgres redis caddy`, then deploy. A Postgres major upgrade is a manual job.
- The GitHub actions in the workflows are pinned by version tag, not by commit hash. The server logs in to
  the registry with the job's short-lived token and logs out again at the end.
- One server: a server failure means downtime until you restore (backups + Hetzner snapshots help). No high availability.
- Images are x86 (`amd64`) only. ARM servers need `platforms: linux/arm64` in `deploy.yml`.
- The deploy and rollback scripts are tested with a stub of Docker, not against a real Docker daemon.
  Your first real deploy is the real test: do it on a staging server or before you have customers.
- `DEMO_ENABLED` should be `false` on a real product.
