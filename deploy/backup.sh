#!/usr/bin/env bash
# Database backup. Runs ON THE SERVER: every night from cron, and before every deploy.
#
#   ./backup.sh            nightly backup
#   ./backup.sh predeploy  the same, with a label (the deploy does this)
#
# pg_dump -> encrypted with BACKUP_PASSPHRASE (AES-256) -> uploaded to the SEPARATE backup
# bucket -> backups older than 14 days are deleted (the newest 3 are always kept).
# Nothing is written to the server's disk. Restore: ./restore-test.sh (also proves it works).

set -euo pipefail
cd "$(dirname "$0")"

label=${1:-nightly}
[[ "$label" =~ ^[a-z0-9-]{1,20}$ ]] || {
  echo "Bad label: $label" >&2
  exit 1
}

env_value() { grep -E "^$1=" .env.backup | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' || true; }

[ -f .env.backup ] || {
  echo "/opt/app/.env.backup is missing. Copy .env.backup.example to .env.backup and fill it in (deploy/server-setup.md, step 12)." >&2
  exit 1
}
BACKUP_PASSPHRASE=$(env_value BACKUP_PASSPHRASE)
HEALTHCHECK_URL=$(env_value HEALTHCHECK_URL)
[ -n "$BACKUP_PASSPHRASE" ] || {
  echo "BACKUP_PASSPHRASE is empty in .env.backup" >&2
  exit 1
}
export BACKUP_PASSPHRASE
# The backup bucket keys go only to the short-lived helper container (not to the app containers).
for v in BACKUP_S3_ENDPOINT BACKUP_S3_REGION BACKUP_S3_BUCKET BACKUP_S3_ACCESS_KEY BACKUP_S3_SECRET_KEY; do
  export "$v=$(env_value "$v")"
done
export IMAGE_TAG=${IMAGE_TAG:-$(tr -d '[:space:]' <.deployed_tag 2>/dev/null || echo none)}

name="db-$(date -u +%Y-%m-%dT%H%MZ)-${label}.dump.enc"
store() { docker compose run --rm -T --no-deps -e BACKUP_S3_ENDPOINT -e BACKUP_S3_REGION -e BACKUP_S3_BUCKET -e BACKUP_S3_ACCESS_KEY -e BACKUP_S3_SECRET_KEY backend python -m app.scripts.backup_store "$@"; }

ping_health() { # $1 = "" (ok) or "/fail"
  [ -n "$HEALTHCHECK_URL" ] && curl -fsS -m 10 --retry 3 -o /dev/null "${HEALTHCHECK_URL}$1" || true
}

fail() {
  echo "BACKUP FAILED: $1" >&2
  store delete "$name" >/dev/null 2>&1 || true # never leave a half-written backup behind
  ping_health "/fail"
  exit 1
}

echo "Backing up to $name"
if ! docker compose exec -T postgres pg_dump -U app -d app -Fc --no-owner |
  openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -pass env:BACKUP_PASSPHRASE |
  store upload "$name"; then
  fail "dump, encryption or upload did not finish"
fi

# A dump of a real database is never tiny (an empty encrypted stream is about 30 bytes).
size=$(store size "$name" 2>/dev/null || echo 0)
if [ "$size" -lt 1024 ]; then
  fail "the uploaded backup is empty or missing"
fi

store prune --keep-days 14
ping_health ""
echo "Backup done: $name ($((size / 1024)) KB)"
