#!/usr/bin/env bash
# Tests the LOGIC of deploy.sh with a pretend `docker` (no Docker, no server needed):
#   bash deploy/tests/deploy-script-test.sh
# It cannot prove that real Docker behaves the same; the first real deploy does that.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
pass=0
failures=0

check() { # check "description" command...
  local desc=$1
  shift
  if "$@"; then
    pass=$((pass + 1))
  else
    printf 'FAIL: %s\n' "$desc"
    failures=$((failures + 1))
  fi
}
called() { grep -q -- "$1" "$FAKE_DIR/calls.log"; }
not_called() { ! grep -q -- "$1" "$FAKE_DIR/calls.log"; }
before() { # line number of the first call matching $1 is smaller than that of $2
  local a b
  a=$(grep -n -m1 -- "$1" "$FAKE_DIR/calls.log" | cut -d: -f1)
  b=$(grep -n -m1 -- "$2" "$FAKE_DIR/calls.log" | cut -d: -f1)
  [ -n "$a" ] && [ -n "$b" ] && [ "$a" -lt "$b" ]
}

new_server() { # a fresh /opt/app look-alike with an old version already running
  work=$(mktemp -d)
  export FAKE_DIR="$work/fake"
  mkdir -p "$FAKE_DIR" "$work/bin" "$work/app"
  cp "$here/fake-docker" "$work/bin/docker"
  chmod +x "$work/bin/docker"
  # curl must never touch the network
  printf '#!/usr/bin/env bash\nexit 1\n' >"$work/bin/curl"
  chmod +x "$work/bin/curl"
  cp "$here/../deploy.sh" "$work/app/deploy.sh"
  # shellcheck disable=SC2016 # the single quotes are on purpose: this writes a script
  {
    echo '#!/usr/bin/env bash'
    echo "echo \"backup.sh \$*\" >>\"$FAKE_DIR/calls.log\""
    echo '[ "${FAIL_BACKUP:-0}" = 1 ] && exit 1'
    echo 'exit 0'
  } >"$work/app/backup.sh"
  chmod +x "$work/app/deploy.sh" "$work/app/backup.sh"
  printf 'DOMAIN=example.com\nPOSTGRES_APP_PASSWORD=apppw\n' >"$work/app/.env"
  mkdir -p "$work/app/secrets"
  ADMIN_PW=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
  printf '%s\n' "$ADMIN_PW" >"$work/app/secrets/postgres_admin_password"
  : >"$FAKE_DIR/calls.log"
  for svc in backend frontend worker beat; do echo "old-$svc" >"$FAKE_DIR/ids-$svc"; done
  echo "sha-old0001" >"$work/app/.deployed_tag"
  export PATH="$work/bin:$PATH"
}

run_deploy() { (cd "$work/app" && ./deploy.sh deploy "$1") >"$work/out.log" 2>&1; }

# ---------------------------------------------------------------- 1. happy path
new_server
check "deploy succeeds" run_deploy sha-new0002
check "backup runs before the migration" before "backup.sh predeploy" "alembic upgrade head"
check "database user is set up after the backup" before "backup.sh predeploy" "python -m app.scripts.db_roles"
check "database user is set up before the migration" before "python -m app.scripts.db_roles" "alembic upgrade head"
check "the admin connection reached both role setups and the migration" test "$(grep -c ADMIN_URL_OK "$FAKE_DIR/calls.log")" = 3
check "roles are set up again after the migration (new tables)" test "$(grep -c 'python -m app.scripts.db_roles' "$FAKE_DIR/calls.log")" = 2
check "the last role setup comes after the migration" test "$(grep -n 'python -m app.scripts.db_roles\|alembic upgrade head' "$FAKE_DIR/calls.log" | tail -1 | grep -c db_roles)" = 1
check "no other container got the admin connection" not_called "ADMIN_URL_LEAK"
check "the admin password is never on a command line" not_called "$ADMIN_PW"
check "migration runs before the switch" before "alembic upgrade head" "--scale backend=2"
check "backend is started next to the old one" called "--scale backend=2"
check "frontend is started next to the old one" called "--scale frontend=2"
check "old backend container is stopped and removed" called "docker stop --time 30 old-backend"
check "no rollback happened" not_called "sha-old0001 -"
check "state file has the new tag" grep -qx "sha-new0002" "$work/app/.deployed_tag"
check "previous tag is remembered" grep -qx "sha-old0001" "$work/app/.previous_tag"
check "only new backend container is left" test "$(cat "$FAKE_DIR/ids-backend")" = "new-backend-sha-new0002-2"

# ---------------------------------------------------------------- 2. migration fails
new_server
export FAIL_MIGRATE=1
check "deploy fails when the migration fails" bash -c "! (cd '$work/app' && ./deploy.sh deploy sha-new0002) >'$work/out.log' 2>&1"
unset FAIL_MIGRATE
check "nothing was switched after a failed migration" not_called "--scale"
check "old tag is still recorded" grep -qx "sha-old0001" "$work/app/.deployed_tag"
check "old backend container still there" test "$(cat "$FAKE_DIR/ids-backend")" = "old-backend"

# ---------------------------------------------------------------- 3. backup fails
new_server
export FAIL_BACKUP=1
check "deploy stops when the backup fails" bash -c "! (cd '$work/app' && ./deploy.sh deploy sha-new0002) >'$work/out.log' 2>&1"
unset FAIL_BACKUP
check "no migration after a failed backup" not_called "alembic"

# ---------------------------------------------------------------- 4. new backend never gets healthy
new_server
export FAIL_SCALE=backend FAIL_TAG=sha-new0002
check "deploy fails when the new backend is unhealthy" bash -c "! (cd '$work/app' && ./deploy.sh deploy sha-new0002) >'$work/out.log' 2>&1"
unset FAIL_SCALE FAIL_TAG
check "the failed new container was removed" called "docker rm -f new-backend-sha-new0002-2"
check "the old version was started again (rollback)" called "\[sha-old0001\] docker compose up .*--scale backend=2"
check "backend ends on the OLD version" test "$(cat "$FAKE_DIR/ids-backend")" = "new-backend-sha-old0001-2"
check "state file still has the old tag" grep -qx "sha-old0001" "$work/app/.deployed_tag"
check "the deploy said it went back" grep -q "Going back to sha-old0001" "$work/out.log"

# ---------------------------------------------------------------- 5. first deploy (nothing before)
new_server
rm -f "$work/app/.deployed_tag" "$FAKE_DIR"/ids-*
check "first deploy succeeds" run_deploy sha-first01
check "no backup on the very first deploy" not_called "backup.sh"
check "state file written" grep -qx "sha-first01" "$work/app/.deployed_tag"

# ---------------------------------------------------------------- 6. manual rollback
new_server
echo "sha-new0002" >"$work/app/.deployed_tag"
echo "sha-old0001" >"$work/app/.previous_tag"
check "rollback succeeds" bash -c "cd '$work/app' && ./deploy.sh rollback >'$work/out.log' 2>&1"
check "rollback swaps the state files" grep -qx "sha-old0001" "$work/app/.deployed_tag"
check "rollback remembers the version it left" grep -qx "sha-new0002" "$work/app/.previous_tag"

# ---------------------------------------------------------------- 7. input checks
new_server
check "a strange tag is refused" bash -c "! (cd '$work/app' && ./deploy.sh deploy 'x; rm -rf /') >'$work/out.log' 2>&1"
check "no tag is refused" bash -c "! (cd '$work/app' && ./deploy.sh deploy) >'$work/out.log' 2>&1"

# ---------------------------------------------------------------- 8. rollback by tag: database is newer
new_server
export FAKE_DB_REV=rev9999
check "deploy of an older version succeeds" run_deploy sha-old0000
check "migrations are skipped when the database is newer" not_called "alembic upgrade"
check "it still switches the version" called "--scale backend=2"
check "it says why" grep -q "Skipping migrations" "$work/out.log"
unset FAKE_DB_REV
new_server
export FAKE_DB_REV=rev0001
check "known database revision: migrations run" run_deploy sha-new0002
check "migration was run" called "alembic upgrade head"
unset FAKE_DB_REV

# ---------------------------------------------------------------- 9. bad Caddyfile
new_server
export FAIL_CADDY=1
check "deploy stops on a bad Caddyfile" bash -c "! (cd '$work/app' && ./deploy.sh deploy sha-new0002) >'$work/out.log' 2>&1"
unset FAIL_CADDY
check "nothing changed after a bad Caddyfile" not_called "alembic"
check "no backup after a bad Caddyfile" not_called "backup.sh"

# ---------------------------------------------------------------- 10. admin password file problems
new_server
rm "$work/app/secrets/postgres_admin_password"
check "deploy refuses when the admin password file is missing" bash -c "! (cd '$work/app' && ./deploy.sh deploy sha-new0002) >'$work/out.log' 2>&1"
check "it says which file" grep -q "postgres_admin_password is missing" "$work/out.log"
check "nothing was pulled or changed" not_called "compose pull"
new_server
echo "short" >"$work/app/secrets/postgres_admin_password"
check "deploy refuses a weak admin password" bash -c "! (cd '$work/app' && ./deploy.sh deploy sha-new0002) >'$work/out.log' 2>&1"
check "weak password: nothing was pulled" not_called "compose pull"

# ---------------------------------------------------------------- 11. admin password must not be in .env
new_server
printf 'POSTGRES_PASSWORD=%s\n' "$ADMIN_PW" >>"$work/app/.env"
check "deploy refuses POSTGRES_PASSWORD in .env" bash -c "! (cd '$work/app' && ./deploy.sh deploy sha-new0002) >'$work/out.log' 2>&1"
check "it explains why" grep -q "must not be in /opt/app/.env" "$work/out.log"
check "nothing was pulled for a leaky .env" not_called "compose pull"
check "the password is not repeated in the message" bash -c "! grep -q '$ADMIN_PW' '$work/out.log'"
new_server
printf 'MIGRATION_DATABASE_URL=postgresql+psycopg://app:x@postgres/app\n' >>"$work/app/.env"
check "deploy refuses MIGRATION_DATABASE_URL in .env" bash -c "! (cd '$work/app' && ./deploy.sh deploy sha-new0002) >'$work/out.log' 2>&1"
new_server
printf 'export POSTGRES_PASSWORD=%s\n' "$ADMIN_PW" >>"$work/app/.env"
check "deploy refuses 'export POSTGRES_PASSWORD=' (compose accepts it)" bash -c "! (cd '$work/app' && ./deploy.sh deploy sha-new0002) >'$work/out.log' 2>&1"
new_server
printf '  POSTGRES_PASSWORD = %s\n' "$ADMIN_PW" >>"$work/app/.env"
check "deploy refuses 'POSTGRES_PASSWORD =' with spaces" bash -c "! (cd '$work/app' && ./deploy.sh deploy sha-new0002) >'$work/out.log' 2>&1"

# ---------------------------------------------------------------- 12. database user setup fails
new_server
export FAIL_ROLES=1
check "deploy stops when the database user setup fails" bash -c "! (cd '$work/app' && ./deploy.sh deploy sha-new0002) >'$work/out.log' 2>&1"
unset FAIL_ROLES
check "no migration after a failed setup" not_called "alembic upgrade"
check "nothing was switched after a failed setup" not_called "--scale"
check "the old tag is still recorded" grep -qx "sha-old0001" "$work/app/.deployed_tag"

# ---------------------------------------------------------------- 13. rollback by tag to a version older than 5B
new_server
export FAKE_OLD_IMAGE=1 FAKE_DB_REV=rev9999
check "deploy of a pre-5B version succeeds" run_deploy sha-old0000
unset FAKE_OLD_IMAGE FAKE_DB_REV
check "the setup is skipped, with a warning" grep -q "older than phase 5B" "$work/out.log"
check "the setup command was not run" not_called "python -m app.scripts.db_roles"
check "it still switches the version" called "--scale backend=2"

# ---------------------------------------------------------------- 14. ./deploy.sh db-roles
new_server
check "db-roles command works" bash -c "cd '$work/app' && ./deploy.sh db-roles >'$work/out.log' 2>&1"
check "it makes sure Postgres runs first" before "up -d --wait --wait-timeout 120 postgres" "python -m app.scripts.db_roles"
check "it ran the setup with the admin connection" called "ADMIN_URL_OK"
check "it does not switch or migrate anything" bash -c "! grep -q -e '--scale' -e 'alembic' '$FAKE_DIR/calls.log'"

printf '\n%d checks passed, %d failed\n' "$pass" "$failures"
[ "$failures" = 0 ]
