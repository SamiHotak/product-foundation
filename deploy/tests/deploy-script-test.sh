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
  printf 'DOMAIN=example.com\n' >"$work/app/.env"
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

printf '\n%d checks passed, %d failed\n' "$pass" "$failures"
[ "$failures" = 0 ]
