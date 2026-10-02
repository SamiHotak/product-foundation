#!/usr/bin/env bash
# Deploy script. Runs ON THE SERVER in /opt/app (GitHub Actions calls it over SSH; you can also
# run it by hand).
#
#   ./deploy.sh deploy sha-abc1234   pull that version, back up, migrate, switch, check
#   ./deploy.sh rollback             go back to the version that ran before
#   ./deploy.sh status               what runs now
#   ./deploy.sh logs backend         follow logs of one service (Ctrl+C to stop)
#   ./deploy.sh reload-caddy         apply a changed Caddyfile
#   ./deploy.sh db-roles             (re)create the limited database user the app runs as
#   ./deploy.sh compose ps           any `docker compose` command with the right settings
#
# How a deploy stays (almost) invisible to visitors:
#   1. The database is backed up, then migrations run while the OLD version still serves.
#   2. backend and frontend: the NEW container starts NEXT TO the old one. Only when it is
#      healthy does the old one get stopped (it finishes its running requests first).
#   3. If anything fails, the previous version is started again automatically.
#
# Migrations are NOT undone by a rollback. So every migration must work with the old code too
# (add columns before using them, remove them one deploy later). See docs/DEPLOYMENT.md.

set -euo pipefail
cd "$(dirname "$0")"

CURRENT_FILE=.deployed_tag
PREVIOUS_FILE=.previous_tag
ADMIN_PASSWORD_FILE=secrets/postgres_admin_password

log() { printf '\n==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

dc() { docker compose "$@"; }

read_tag() {
  if [ -s "$1" ]; then tr -d '[:space:]' <"$1"; fi
}

env_value() { # read one value from .env without running it as a script
  grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' || true
}

valid_tag() { [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]; }

# --- the two database users (docs/SECURITY.md) ----------------------------------------------
# The app runs as the limited user "app_rt". Only this script uses the Postgres ADMIN user
# ("app") to change tables (migrations). The admin password is the FILE $ADMIN_PASSWORD_FILE:
# only the postgres container and this script read it, never an app container.

admin_database_url() {
  local pw
  [ -s "$ADMIN_PASSWORD_FILE" ] ||
    die "$ADMIN_PASSWORD_FILE is missing or empty (deploy/server-setup.md, step 10)."
  pw=$(tr -d '[:space:]' <"$ADMIN_PASSWORD_FILE")
  [[ "$pw" =~ ^[A-Za-z0-9]{32,}$ ]] ||
    die "$ADMIN_PASSWORD_FILE must hold 32 or more letters and digits (make it with: openssl rand -hex 32)."
  printf 'postgresql+psycopg://app:%s@postgres:5432/app' "$pw"
}

# A one-off backend container WITH the admin connection (migrations only). The URL goes in through
# the environment (-e NAME, no value), so the password is never part of a command line.
admin_run() {
  local url
  url=$(admin_database_url) || return 1
  (
    export MIGRATION_DATABASE_URL=$url
    dc run --rm -T --no-deps -e MIGRATION_DATABASE_URL backend "$@"
  )
}

# Create/update the limited database user. Runs before every migration (safe to repeat). An image
# from before phase 5B does not have the command (a rollback by tag): then it is skipped.
ensure_db_roles() {
  local rc=0
  dc run --rm -T --no-deps backend python -c \
    "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('app.scripts.db_roles') else 3)" \
    >/dev/null 2>&1 || rc=$?
  if [ "$rc" = 3 ]; then
    warn "$IMAGE_TAG has no database-user setup (older than phase 5B). Skipping it."
    return 0
  fi
  [ "$rc" = 0 ] || return 1
  admin_run python -m app.scripts.db_roles
}

# The admin password must never reach an app container: they all read .env.
check_env_layout() {
  local name
  for name in POSTGRES_PASSWORD MIGRATION_DATABASE_URL; do
    # compose's .env parser also accepts "export NAME=" and "NAME =", so look for those too
    ! grep -Eq "^[[:space:]]*(export[[:space:]]+)?${name}[[:space:]]*=" .env ||
      die "$name must not be in /opt/app/.env (every app container reads that file). Delete the line. The admin password is the file $ADMIN_PASSWORD_FILE (deploy/server-setup.md, step 10)."
  done
}

# --- health checks ------------------------------------------------------------------------

# True when the API (with Postgres + Redis) and the website answer, from inside the containers.
services_answer() {
  dc exec -T backend python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=5).status == 200 else 1)" >/dev/null 2>&1 &&
    dc exec -T frontend node -e "fetch('http://127.0.0.1:3000/robots.txt').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" >/dev/null 2>&1
}

wait_until_healthy() {
  local _
  for _ in $(seq 1 30); do
    services_answer && return 0
    sleep 2
  done
  return 1
}

# True when every app container runs the expected version (no old container left over).
versions_match() {
  local svc image
  for svc in backend frontend worker beat; do
    for image in $(dc ps "$svc" --format '{{.Image}}'); do
      [[ "$image" == *":$IMAGE_TAG" ]] || return 1
    done
  done
}

# --- switching one service ----------------------------------------------------------------

# backend / frontend: start the new container next to the old one, stop the old one only when
# the new one is healthy. Returns 1 (and removes the new container) if it never gets healthy.
rollout_web() {
  local svc=$1 old_ids all_ids new_ids count id
  old_ids=$(dc ps -q "$svc" | tr '\n' ' ')
  if [ -z "${old_ids// /}" ]; then # first start
    dc up -d --no-deps --wait --wait-timeout 180 "$svc"
    return
  fi
  count=$(wc -w <<<"$old_ids")
  if ! dc up -d --no-deps --no-recreate --scale "$svc=$((count * 2))" --wait --wait-timeout 180 "$svc"; then
    warn "The new $svc container did not become healthy. Removing it; the old one keeps serving."
    all_ids=$(dc ps -aq "$svc" | tr '\n' ' ')
    for id in $all_ids; do
      [[ " $old_ids " == *" $id "* ]] || docker rm -f "$id" >/dev/null 2>&1 || true
    done
    return 1
  fi
  new_ids=""
  for id in $(dc ps -q "$svc"); do
    [[ " $old_ids " == *" $id "* ]] || new_ids="$new_ids $id"
  done
  sleep 3 # both serve for a moment
  # shellcheck disable=SC2086 # the ids are words on purpose
  docker stop --time 30 $old_ids >/dev/null
  # shellcheck disable=SC2086
  docker rm $old_ids >/dev/null
  dc up -d --no-deps --no-recreate --scale "$svc=$count" "$svc" >/dev/null
}

# worker / beat: a plain restart (a running job gets 2 minutes to finish, then it is retried).
rollout_background() {
  dc up -d --no-deps --wait --wait-timeout 240 "$1"
}

switch_all() {
  local svc
  for svc in backend frontend; do
    log "Switching $svc to $IMAGE_TAG"
    rollout_web "$svc" || return 1
  done
  for svc in worker beat; do
    log "Restarting $svc on $IMAGE_TAG"
    rollout_background "$svc" || return 1
  done
}

reload_caddy() {
  dc up -d --no-deps caddy
  dc exec -T caddy caddy reload --config /etc/caddy/Caddyfile
}

# Runs the migrations of the version that is about to start. When the database is NEWER than that
# version (a rollback by tag after a release that had a migration), the old image does not know
# the database revision and alembic would fail. Then we skip: the expand/contract rule
# (docs/DEPLOYMENT.md) makes the old code work with the newer database.
run_migrations() {
  local db_rev
  db_rev=$(dc exec -T postgres psql -U app -d app -tAc 'SELECT version_num FROM alembic_version' 2>/dev/null | tr -d '[:space:]') || db_rev=""
  if [ -n "$db_rev" ] && ! dc run --rm -T --no-deps backend alembic history 2>/dev/null | grep -q "$db_rev"; then
    warn "The database (revision $db_rev) is newer than $IMAGE_TAG. Skipping migrations (this looks like a rollback)."
    return 0
  fi
  admin_run alembic upgrade head
}

# --- commands -----------------------------------------------------------------------------

cmd_deploy() {
  local tag=${1:-} previous
  [ -n "$tag" ] || die "Usage: ./deploy.sh deploy <image tag>, e.g. sha-abc1234"
  valid_tag "$tag" || die "Strange image tag: $tag"
  [ -f .env ] || die "/opt/app/.env is missing. See deploy/server-setup.md."
  check_env_layout
  admin_database_url >/dev/null # fail early (before anything is pulled or changed) if the file is wrong
  export IMAGE_TAG=$tag
  previous=$(read_tag "$CURRENT_FILE")

  dc config -q || die "docker-compose.yml or .env has a problem (see above)."

  # Only our own images are pulled. postgres, redis and caddy are pulled only when missing (the
  # first deploy), so a new upstream image never restarts the database during a deploy.
  # To update them on purpose: ./deploy.sh compose pull postgres redis caddy   (then deploy).
  log "Pulling images for $tag"
  dc pull --quiet backend frontend

  log "Checking the Caddy configuration"
  dc run --rm -T --no-deps caddy caddy validate --config /etc/caddy/Caddyfile ||
    die "The Caddyfile has a problem (see above). Nothing was changed."

  log "Starting Postgres and Redis (no change if they already run)"
  dc up -d --wait --wait-timeout 120 postgres redis

  if [ -n "$previous" ] && [ "${SKIP_BACKUP:-0}" != "1" ]; then
    log "Backing up the database before the update"
    ./backup.sh predeploy || die "The backup failed, so nothing was changed. Fix the backup first (or SKIP_BACKUP=1 at your own risk)."
  fi

  log "Setting up the limited database user (no change if it exists)"
  ensure_db_roles ||
    die "Database user setup failed. Nothing was switched: the old version still runs."

  log "Running database migrations (the old version still serves)"
  run_migrations ||
    die "Migration failed. Nothing was switched: the old version still runs. The database was backed up just before."

  # The migrations may have created tables (on the very first deploy: the migration history table too).
  # Run the role setup again so the app user gets exactly the intended rights on them.
  ensure_db_roles ||
    die "Database user setup failed after the migrations. Nothing was switched: the old version still runs."

  if ! switch_all || ! wait_until_healthy || ! versions_match; then
    warn "The new version is not healthy."
    if [ -n "$previous" ]; then
      warn "Going back to $previous."
      IMAGE_TAG=$previous switch_all || true
      IMAGE_TAG=$previous wait_until_healthy || warn "The old version does not answer either! Look at: ./deploy.sh logs backend"
    fi
    die "Deploy of $tag FAILED."
  fi

  log "Applying the Caddy configuration"
  reload_caddy || warn "Caddy could not reload its configuration (see above). The old configuration keeps running."

  # A last look through Caddy. Only a warning: on the very first deploy the HTTPS certificate
  # may not exist yet. GitHub Actions makes the strict public check.
  local domain
  domain=$(env_value DOMAIN)
  if curl -fsS -k -m 10 --resolve "$domain:443:127.0.0.1" "https://$domain/api/health/ready" >/dev/null 2>&1; then
    log "Through Caddy: OK"
  else
    warn "https://$domain did not answer from this server yet (a new certificate can take a minute)."
  fi

  [ -n "$previous" ] && [ "$previous" != "$tag" ] && printf '%s\n' "$previous" >"$PREVIOUS_FILE"
  printf '%s\n' "$tag" >"$CURRENT_FILE"

  # Old images pile up (a few hundred MB each). Keep two weeks for quick rollbacks.
  docker image prune -af --filter "until=336h" >/dev/null 2>&1 || true

  log "Deployed $tag (before: ${previous:-nothing})"
}

cmd_rollback() {
  local current previous
  current=$(read_tag "$CURRENT_FILE")
  previous=$(read_tag "$PREVIOUS_FILE")
  [ -n "$previous" ] || die "There is no previous version to go back to."
  export IMAGE_TAG=$previous
  log "Rolling back: $current -> $previous"
  dc pull --quiet backend frontend || warn "Could not pull; using the images already on this server."
  switch_all || die "Rollback failed. Look at: ./deploy.sh logs backend"
  wait_until_healthy || die "Rolled back, but the services do not answer. Look at: ./deploy.sh logs backend"
  reload_caddy || warn "Caddy could not reload."
  printf '%s\n' "$current" >"$PREVIOUS_FILE"
  printf '%s\n' "$previous" >"$CURRENT_FILE"
  log "Now running $previous. Database migrations were NOT undone (see docs/DEPLOYMENT.md)."
}

cmd_db_roles() {
  check_env_layout
  dc up -d --wait --wait-timeout 120 postgres
  ensure_db_roles || die "Database user setup failed (see above)."
  log "The limited database user is ready."
}

cmd_status() {
  printf 'Running version:  %s\n' "$(read_tag "$CURRENT_FILE")"
  printf 'Version before:   %s\n\n' "$(read_tag "$PREVIOUS_FILE")"
  dc ps
  printf '\n'
  df -h / | tail -1 | awk '{print "Disk: " $3 " used of " $2 " (" $5 ")"}'
  free -m | awk '/Mem:/ {print "RAM:  " $3 " MB used of " $2 " MB"}'
}

main() {
  local command=${1:-help}
  shift || true
  case "$command" in
    deploy) cmd_deploy "$@" ;;
    rollback) cmd_rollback ;;
    status | logs | reload-caddy | compose | db-roles)
      IMAGE_TAG=$(read_tag "$CURRENT_FILE")
      export IMAGE_TAG=${IMAGE_TAG:-none}
      case "$command" in
        status) cmd_status ;;
        logs) dc logs -f --tail=100 "$@" ;;
        reload-caddy) reload_caddy ;;
        compose) dc "$@" ;;
        db-roles) cmd_db_roles ;;
      esac
      ;;
    *) sed -n '2,11p' "$0" ;;
  esac
}

main "$@"
