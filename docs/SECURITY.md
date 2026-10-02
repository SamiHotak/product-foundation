# Security checklist

What protects the product, how to check it, and what to do every month or after an incident.
Short version for the server: `bash /opt/app/security-audit.sh` (it only reads, it changes nothing).

## 1. The checklist

Tick these on every real server. The audit script checks the lines marked **[audit]**.

| # | What | Where it comes from |
| - | ---- | ------------------- |
| 1 | SSH: keys only, no passwords, 3 tries, only users `root` and `deploy` **[audit]** | `deploy/harden-server.sh` |
| 2 | Hetzner firewall: only ports 22, 80, 443 (TCP) and 443 (UDP); `ufw` as a second layer **[audit]** | `deploy/server-setup.md` steps 4 and 5 |
| 3 | fail2ban bans an address for 1 hour after 4 wrong SSH logins (longer for repeaters) **[audit]** | `harden-server.sh` |
| 4 | Ubuntu security updates install by themselves, no automatic reboot **[audit]** | `harden-server.sh` |
| 5 | Database: the app uses the limited user `app_rt`, not the admin **[audit]** | section 2 below |
| 6 | Containers: no extra Linux rights (`cap_drop: ALL`, `no-new-privileges`) **[audit]** | `deploy/docker-compose.yml` |
| 7 | Only Caddy publishes ports (80/443); Postgres and Redis are not reachable from outside **[audit]** | `docker-compose.yml` |
| 8 | `.env` and `.env.backup` can only be read by their owner (mode 600); `secrets/` is mode 700 **[audit]** | `harden-server.sh` |
| 9 | Backups run nightly, are encrypted, use their own keys, and a restore was tested **[audit: cron + log age]** | `docs/DEPLOYMENT.md` |
| 10 | HTTPS with a valid certificate; security headers; http redirects to https **[audit]** | Caddy |
| 11 | Only `main` can deploy; the deploy key is in a protected GitHub environment | `server-setup.md` step 11 |
| 12 | Secrets are rotated on a schedule (section 3) | this file |

## 2. The database has two users

| User | Used by | May do | Password lives in |
| ---- | ------- | ------ | ----------------- |
| `app_rt` | API, worker, beat | read and write rows (`SELECT/INSERT/UPDATE/DELETE`), use sequences | `POSTGRES_APP_PASSWORD` in `.env` |
| `app` (admin) | `deploy.sh` only: migrations, backups, restore | everything | file `/opt/app/secrets/postgres_admin_password` (never in `.env`, never in an app container) |

Why: if someone finds a hole in the app (for example SQL injection or a stolen container), they get
what the app can reach. With `app_rt` that is the rows, **not** the database server: no creating or
dropping tables, no extensions, no `COPY ... PROGRAM` (running commands), no superuser powers,
no changing the migration history, no bypassing row security. Tenant isolation is still enforced in the app
code and tests; this is a second wall, not a replacement.

- `ensure_db_roles` runs on **every deploy**: after the backup and before the migrations, and again after them (new tables, and the migration history table on the first deploy). It runs in one database transaction, so the app that is still running never sees a moment without rights. You can also run it alone:
  `./deploy.sh db-roles`. It is safe to repeat. It fixes the rights of new tables automatically
  (`ALTER DEFAULT PRIVILEGES`).
- The code is `backend/app/db/roles.py`; tests are `backend/tests/test_db_roles.py` (27 tests on a real Postgres).
- The migrations use the admin login through `MIGRATION_DATABASE_URL`. It is passed to the migration
  container as an environment variable of that one command, never on the command line (where `ps` shows it).
- **Honest limit:** the admin password file is mode 644 inside a 700 folder, because the Postgres container
  user must read it. Anybody who is `root` or `deploy` on the server can read it. That is normal (the `deploy` user
  can run Docker, which is the same as root on this server). The point of the split is the app, not the server admin.

## 3. Secret rotation plan

Rotate on the schedule, **and immediately** when a secret may have leaked (a laptop was stolen, a key was pasted
in a chat or ticket, a team member left). Always write the new value to your password manager first.

| Secret | Where | How often | How to rotate | Side effects |
| ------ | ----- | --------- | ------------- | ------------ |
| `SECRET_KEY` | `.env` | yearly | Put a new `openssl rand -hex 32`, deploy. | All users are logged out; open email links stop working. |
| `POSTGRES_APP_PASSWORD` | `.env` | yearly | New value in `.env`, then `./deploy.sh deploy "$(cat .deployed_tag)"` (the deploy runs `db-roles`, which sets the new password, and restarts the app). | A few seconds of errors during the restart. |
| Postgres admin password | `secrets/postgres_admin_password` | yearly | `./deploy.sh compose exec -T postgres psql -U app -d postgres -c "ALTER ROLE app PASSWORD '<new>'"`, then write the same value into the file (`printf %s '<new>' > secrets/postgres_admin_password`). Do both quickly; `deploy.sh` reads the file. | None for the running app. A deploy between the two steps fails (safe: nothing breaks). |
| `REDIS_PASSWORD` | `.env` | yearly | New value in `.env`, deploy. | Queued jobs may be lost. |
| S3 keys (files) | `.env` | yearly | Create a new key pair at Hetzner, put it in `.env`, deploy, then delete the old pair. | None. |
| S3 keys (backups) + `BACKUP_PASSPHRASE` | `.env.backup` | yearly (keys); passphrase only if leaked | New keys: same as above. A new passphrase only protects **new** backups: keep the old one in the password manager as long as old backups exist. | None. |
| Deploy SSH key | GitHub environment secret `DEPLOY_SSH_KEY` + `authorized_keys` of `deploy` | yearly | `ssh-keygen` a new key, add its public key to `authorized_keys`, replace the GitHub secret, run a deploy, then remove the old public key. | None. |
| Your admin SSH key | `authorized_keys` of `root` and `deploy` | when a laptop is lost; otherwise every 2 years | Same idea: add the new one, test a login, remove the old one. | None. |
| Stripe, email, AI provider keys | `.env` | yearly, or when leaked | Roll the key in the provider's dashboard, update `.env`, deploy. | Billing webhooks fail until the new webhook secret is set. |
| Sentry DSN | `.env`, GitHub variable | only if abused | New DSN in Sentry, update both. | None. |

If a secret leaked: rotate first, then look at the logs (`./deploy.sh logs backend`) for use of the old one.

## 4. Every month (10 minutes)

1. `bash /opt/app/security-audit.sh` as root. Fix every `FAIL`, read every `WARN`.
2. `apt update && apt list --upgradable`: if a kernel update needs a reboot, pick a quiet time and `reboot`.
3. Update Docker on purpose (`apt -y upgrade docker-ce docker-ce-cli containerd.io`): it restarts the containers.
4. `./deploy.sh compose pull postgres redis caddy`, then deploy (see `docs/DEPLOYMENT.md`, known limits).
5. Look at GitHub **Security** > Dependabot alerts and update what is marked high.

## 5. What this does NOT cover (honest limits)

- **Tested with pretend commands.** The scripts `harden-server.sh` and `security-audit.sh` are tested with stand-ins
  for `sshd`, `ufw`, `fail2ban` and `docker` (`deploy/tests/server-scripts-test.sh`). Real servers can differ.
  The first run on a real server is the real test: **keep your first SSH window open** until a second login works.
- **No intrusion detection**, no central log collection, no file-integrity monitoring. Docker logs are size-limited.
- **One server, one admin.** Whoever controls the `deploy` key controls the server (Docker access = root).
  That is why only `main` may deploy and the key sits in a protected environment.
- **IPv6 is not used** (see `docs/DEPLOYMENT.md`).
- Port 22 is open to the whole internet (GitHub's addresses change). Keys only + fail2ban make this acceptable.
  If you later move deploys to a fixed runner, restrict port 22 to its address.
- A hacked app can still read and change **all** rows `app_rt` can reach. The two-user split limits the damage to
  that; it does not stop it.
- Automatic updates cover Ubuntu security fixes only, not Docker images or app libraries.
