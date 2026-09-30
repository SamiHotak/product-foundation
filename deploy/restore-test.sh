#!/usr/bin/env bash
# Proves that a backup can really be restored. Runs ON THE SERVER.
#
#   ./restore-test.sh                     newest backup
#   ./restore-test.sh db-2026-...enc      a specific one   (list them: ./restore-test.sh --list)
#   ./restore-test.sh --stdout [name]     print the decrypted dump (used for a real restore)
#
# It restores into a SCRATCH database called restore_test (your real database is not touched),
# prints a few row counts, and drops the scratch database again. Do this once after setting
# up backups, and every few months. A backup that was never restored is only a hope.

set -euo pipefail
cd "$(dirname "$0")"

env_value() { grep -E "^$1=" .env.backup | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' || true; }

[ -f .env.backup ] || {
  echo "/opt/app/.env.backup is missing. See .env.backup.example (deploy/server-setup.md, step 12)." >&2
  exit 1
}
BACKUP_PASSPHRASE=$(env_value BACKUP_PASSPHRASE)
[ -n "$BACKUP_PASSPHRASE" ] || {
  echo "BACKUP_PASSPHRASE is empty in .env.backup" >&2
  exit 1
}
export BACKUP_PASSPHRASE
for v in BACKUP_S3_ENDPOINT BACKUP_S3_REGION BACKUP_S3_BUCKET BACKUP_S3_ACCESS_KEY BACKUP_S3_SECRET_KEY; do
  export "$v=$(env_value "$v")"
done
export IMAGE_TAG=${IMAGE_TAG:-$(tr -d '[:space:]' <.deployed_tag 2>/dev/null || echo none)}

store() { docker compose run --rm -T --no-deps -e BACKUP_S3_ENDPOINT -e BACKUP_S3_REGION -e BACKUP_S3_BUCKET -e BACKUP_S3_ACCESS_KEY -e BACKUP_S3_SECRET_KEY backend python -m app.scripts.backup_store "$@"; }
psql_admin() { docker compose exec -T postgres psql -U app -d postgres -v ON_ERROR_STOP=1 "$@"; }

if [ "${1:-}" = "--list" ]; then
  store list
  exit 0
fi

if [ "${1:-}" = "--stdout" ]; then # the decrypted dump on stdout (for a real restore, docs/DEPLOYMENT.md)
  name=${2:-$(store latest)}
  store download "$name" | openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass env:BACKUP_PASSPHRASE
  exit 0
fi

name=${1:-$(store latest)}
echo "Restoring $name into the scratch database restore_test ..."

psql_admin -q -c "DROP DATABASE IF EXISTS restore_test" -c "CREATE DATABASE restore_test"
cleanup() { psql_admin -q -c "DROP DATABASE IF EXISTS restore_test" >/dev/null 2>&1 || true; }
trap cleanup EXIT

store download "$name" |
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass env:BACKUP_PASSPHRASE |
  docker compose exec -T postgres pg_restore -U app -d restore_test --no-owner --exit-on-error

count() { docker compose exec -T postgres psql -U app -d restore_test -tAc "SELECT count(*) FROM $1" | tr -d '[:space:]'; }
echo
echo "Restore worked. Rows in the restored copy:"
echo "  users:          $(count users)"
echo "  organizations:  $(count organizations)"
echo "  migration:      $(docker compose exec -T postgres psql -U app -d restore_test -tAc 'SELECT version_num FROM alembic_version' | tr -d '[:space:]')"
echo
echo "Compare with the live database: docker compose exec postgres psql -U app -d app -c 'SELECT count(*) FROM users'"
echo "The scratch database is deleted now."
