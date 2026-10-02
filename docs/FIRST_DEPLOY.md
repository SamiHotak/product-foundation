# First real deployment: the plan (for when you have a server)

You have no server and no budget yet. This page is the short map. The click-by-click guide is
[deploy/server-setup.md](../deploy/server-setup.md); this page tells you **what to do now for free**,
**what to do on the day**, and **how to keep the cost very low** while you learn.

## A. What you can do now (free, no server)

| Do now | Why it helps later | How |
| ------ | ------------------ | --- |
| Run the full checks on your PC | Proves the code is healthy | `make check` |
| Run the load test locally | Finds slow code early | `make loadtest-users` / `make loadtest` (`docs/LOADTEST.md`) |
| Create the free accounts | Waiting for ID checks and email confirmations costs days, not money | GitHub (done), Sentry (EU region), Healthchecks.io, UptimeRobot, Resend or Postmark free tier, Stripe in **test mode** |
| Make the SSH keys | Step 2 of the server guide | `ssh-keygen`, keep the private files safe, back them up in your password manager |
| Fill the password manager | You need these values on the day | list: `SECRET_KEY`, `POSTGRES_APP_PASSWORD`, `REDIS_PASSWORD`, admin DB password, `BACKUP_PASSPHRASE` (all `openssl rand -hex 32`, or PowerShell: use any random 64-hex generator) |
| Read the files the server will run | No surprises | `deploy/server-setup.md`, `docs/SECURITY.md`, `docs/DEPLOYMENT.md` |
| Mark the repo as a template | Needed for new products | `docs/NEW_PRODUCT.md`, section 0 |

## B. How to pay almost nothing for the first deployment

Hetzner Cloud servers are billed **by the hour (check)**, and a deleted server stops costing. So you can rehearse:

1. Create the server only when you have a free 3-hour block and everything in section A is ready.
2. Follow `deploy/server-setup.md` completely (hardening, deploy, backup, restore test, audit, load test).
3. If you only want to learn: **delete the server and its volumes the same day** (Hetzner console > server > Delete).
   Cost for one day is typically well below one euro **(check the current price list)**.
4. A real domain costs money (about 1 to 15 EUR per year). For a rehearsal you do not need one: a free
   wildcard DNS name such as `203-0-113-10.sslip.io` (your `SERVER_IP` with dashes) points to your server, and Caddy
   can get a normal certificate for it **(check; the service is run by volunteers, so do not use it for a real product)**.
   Use that name as `DOMAIN` in `.env` and as the GitHub variable `DOMAIN`.
5. Object storage and backups are paid parts of Hetzner. For a one-day rehearsal you can skip the backup bucket
   (do not set up `.env.backup`; the first deploy works without it, but every later deploy stops at the pre-deploy backup unless you run it with `SKIP_BACKUP=1`), and then you **cannot** do the restore test. Do that
   part at least once before real customers. A backup that was never restored is only a hope.

## C. The order on the day

1. Server guide steps 1 to 6 (account, keys, server, firewall, first login, **`harden-server.sh`**, Docker).
2. Step 10: `.env` **and** the admin password file `/opt/app/secrets/postgres_admin_password`. Create the file **before** the first deploy.
3. Steps 11 and 13: GitHub secrets, first deploy.
4. Step 12 and 14: backups, `bash /opt/app/security-audit.sh` (all `OK`).
5. Load test against the server (`docs/LOADTEST.md`, "Run it on a server"), then clean up the test users.
6. Write the result in your progress log: audit result, load test p95, restore test date.

## D. What is certain, what is not

- **Tested for real in the build environment:** the two database users with real migrations, the whole backend test suite running as the limited user, the load test (50 people), the deploy script logic.
- **Tested only with pretend commands:** SSH hardening, firewall checks, fail2ban, Docker commands, the compose file on a real Docker host. The compose file is checked for syntax (`docker compose config`) but never started here.
- **So expect small problems on the first real run.** The most likely ones: the permission of the admin password file inside the Postgres container, a different Ubuntu image detail (an extra SSH config file), and the first image pull. The audit script and the deploy log name the failing line; fix, run again. Keep your first SSH window open while you change SSH.
