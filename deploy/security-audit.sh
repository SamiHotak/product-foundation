#!/usr/bin/env bash
# Security audit of the production server. READ-ONLY: it changes nothing. Run it as root:
#
#   sudo bash /opt/app/security-audit.sh
#
# Run it after harden-server.sh, after the first deploy, and once a month. Every line says PASS,
# WARN (look at it soon), FAIL (fix it now) or SKIP (could not be checked, and why).
# The exit code is 1 when there is at least one FAIL.
#
# For tests only: AUDIT_ROOT=/some/dir reads files from below that directory instead of /.

set -uo pipefail

ROOT=${AUDIT_ROOT:-}
APP="$ROOT/opt/app"
pass=0 warn=0 fail=0 skip=0

ok() { printf 'PASS  %s\n' "$*"; pass=$((pass + 1)); }
bad() { printf 'FAIL  %s\n' "$*"; fail=$((fail + 1)); }
meh() { printf 'WARN  %s\n' "$*"; warn=$((warn + 1)); }
skp() { printf 'SKIP  %s\n' "$*"; skip=$((skip + 1)); }
section() { printf '\n--- %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

env_value() { # one value from /opt/app/.env (never run as a script)
  grep -E "^$1=" "$APP/.env" 2>/dev/null | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' || true
}

# --- SSH --------------------------------------------------------------------------------------

check_ssh() {
  section "SSH"
  local cfg
  if ! have sshd || ! cfg=$(sshd -T 2>/dev/null) || [ -z "$cfg" ]; then
    skp "SSH settings: could not read them (run as root)"
    return
  fi
  want() { # want <key> <description> <allowed values...>
    local key=$1 desc=$2 got v
    shift 2
    got=$(awk -v k="$key" '$1 == k {print $2; exit}' <<<"$cfg")
    for v in "$@"; do
      if [ "$got" = "$v" ]; then
        ok "$desc"
        return
      fi
    done
    bad "$desc (is: ${got:-unset})"
  }
  want passwordauthentication "SSH passwords are off" no
  want kbdinteractiveauthentication "SSH keyboard-interactive login is off" no
  want permitrootlogin "Root may log in only with a key" prohibit-password without-password no
  local tries
  tries=$(awk '$1 == "maxauthtries" {print $2; exit}' <<<"$cfg")
  if [ "${tries:-99}" -le 4 ] 2>/dev/null; then ok "SSH allows at most $tries tries per connection"; else meh "SSH MaxAuthTries is ${tries:-unset} (3 is better)"; fi
  want x11forwarding "X11 forwarding is off" no
}

# --- firewall and open ports ----------------------------------------------------------------------

check_network() {
  section "Firewall and open ports"
  if have ufw; then
    local st
    st=$(ufw status verbose 2>/dev/null || true)
    if grep -q '^Status: active' <<<"$st" && grep -q 'deny (incoming)' <<<"$st"; then
      ok "ufw is active and denies incoming traffic by default"
    else
      bad "ufw is not active, or it does not deny incoming traffic by default"
    fi
  else
    skp "ufw is not installed"
  fi
  if have ss; then
    local proto addr port bad_tcp="" bad_udp=""
    while read -r proto _ _ _ addr _; do
      port=${addr##*:}
      case "$addr" in 127.* | "[::1]"* | "::1"* | *%lo:*) continue ;; esac
      case "$proto" in
        tcp) case "$port" in 22 | 80 | 443) ;; *) bad_tcp="$bad_tcp $addr" ;; esac ;;
        udp) case "$port" in 443 | 68 | 123) ;; *) bad_udp="$bad_udp $addr" ;; esac ;;
      esac
    done < <(ss -H -tuln 2>/dev/null)
    if [ -z "$bad_tcp" ]; then ok "Only ports 22, 80 and 443 listen to the internet (TCP)"; else bad "Unexpected TCP ports listen to the internet:$bad_tcp"; fi
    if [ -z "$bad_udp" ]; then ok "No unexpected UDP ports"; else meh "Unexpected UDP ports:$bad_udp"; fi
  else
    skp "ss is not installed (could not list open ports)"
  fi
}

# --- brute force, updates, clock ---------------------------------------------------------------------

check_host() {
  section "Updates and brute-force protection"
  if have systemctl && [ "$(systemctl is-active fail2ban 2>/dev/null)" = active ]; then
    ok "fail2ban is running"
    if have fail2ban-client && fail2ban-client status sshd >/dev/null 2>&1; then ok "fail2ban watches SSH (jail sshd)"; else bad "fail2ban has no running sshd jail"; fi
  else
    bad "fail2ban is not running"
  fi
  if have apt-config && apt-config dump 2>/dev/null | grep -q 'APT::Periodic::Unattended-Upgrade "1"'; then
    ok "Automatic security updates are on"
  else
    bad "Automatic security updates are off"
  fi
  if [ -e "$ROOT/var/run/reboot-required" ]; then
    meh "A reboot is needed to finish updates (do it at a quiet time: reboot)"
  else
    ok "No reboot is pending"
  fi
  if have timedatectl; then
    if [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = yes ]; then ok "The clock is synchronised"; else meh "The clock is not synchronised"; fi
  else
    skp "timedatectl is not installed (clock not checked)"
  fi
}

# --- files ------------------------------------------------------------------------------------------

mode_of() { stat -c %a "$1" 2>/dev/null; }

check_files() {
  section "Secrets on disk"
  local f m
  for f in .env .env.backup; do
    if [ -f "$APP/$f" ]; then
      m=$(mode_of "$APP/$f")
      if [ "$m" = 600 ]; then ok "$f can only be read by its owner"; else bad "$f has mode $m (must be 600: chmod 600 /opt/app/$f)"; fi
    elif [ "$f" = .env ]; then
      bad "/opt/app/.env is missing"
    else
      meh "/opt/app/.env.backup is missing: no backups can run"
    fi
  done
  if [ -d "$APP/secrets" ]; then
    m=$(mode_of "$APP/secrets")
    if [ "$m" = 700 ]; then ok "secrets/ is closed for everybody except its owner"; else bad "secrets/ has mode $m (must be 700)"; fi
    if [ -s "$APP/secrets/postgres_admin_password" ]; then
      ok "The Postgres admin password file exists"
    else
      bad "secrets/postgres_admin_password is missing or empty"
    fi
  else
    bad "/opt/app/secrets is missing (the Postgres admin password lives there)"
  fi
  if [ -f "$APP/.env" ]; then
    local name found=0
    for name in POSTGRES_PASSWORD MIGRATION_DATABASE_URL; do
      # compose's .env parser also accepts "export NAME=" and "NAME =", so look for those too
      if grep -Eq "^[[:space:]]*(export[[:space:]]+)?${name}[[:space:]]*=" "$APP/.env"; then
        bad "$name is in .env: every app container could read the admin database login"
        found=1
      fi
    done
    [ "$found" = 1 ] || ok ".env holds no admin database login"
    if [ "$(env_value DEMO_ENABLED)" = true ]; then meh "DEMO_ENABLED=true: a public demo is on (fine for a showcase, not for a product with customers)"; else ok "The public demo is off"; fi
  fi
}

# --- containers -------------------------------------------------------------------------------------------

check_docker() {
  section "Containers and database"
  if ! have docker || ! docker ps >/dev/null 2>&1; then
    skp "Docker is not reachable (run as root or as a user in the docker group)"
    return
  fi
  local line published="" name
  while read -r line; do
    case "$line" in *"0.0.0.0:"* | *":::"*)
      for p in $(grep -oE '(0\.0\.0\.0|:::):[0-9]+->' <<<"$line" | grep -oE ':[0-9]+->' | tr -d ':>-'); do
        case "$p" in 80 | 443) ;; *) published="$published $p" ;; esac
      done ;;
    esac
  done < <(docker ps --format '{{.Names}} {{.Ports}}')
  if [ -z "$published" ]; then ok "Containers publish only ports 80 and 443"; else bad "Containers publish other ports to the internet:$published"; fi

  local admin_pw="" apps
  [ -s "$APP/secrets/postgres_admin_password" ] && admin_pw=$(tr -d '[:space:]' <"$APP/secrets/postgres_admin_password")
  apps=$(docker ps --format '{{.Names}}' | grep -E '^app-(backend|worker|beat|frontend)-[0-9]+$' || true)
  if [ -z "$apps" ]; then
    skp "No app containers are running (before the first deploy?)"
  else
    local hardened=1 leaked=0 envdump
    for name in $apps; do
      docker inspect -f '{{.HostConfig.CapDrop}} {{.HostConfig.SecurityOpt}}' "$name" 2>/dev/null | grep -q 'ALL' &&
        docker inspect -f '{{.HostConfig.SecurityOpt}}' "$name" 2>/dev/null | grep -q 'no-new-privileges' || hardened=0
      envdump=$(docker exec "$name" printenv 2>/dev/null || true)
      if grep -qE '^(POSTGRES_PASSWORD|MIGRATION_DATABASE_URL)=' <<<"$envdump"; then leaked=1; fi
      if [ -n "$admin_pw" ] && grep -qFf <(printf '%s\n' "$admin_pw") <<<"$envdump"; then leaked=1; fi
    done
    if [ "$hardened" = 1 ]; then ok "App containers have no extra Linux rights (cap_drop ALL, no-new-privileges)"; else meh "Some app container still has extra Linux rights (is docker-compose.yml up to date?)"; fi
    if [ "$leaked" = 0 ]; then ok "The Postgres admin login is not visible inside the app containers"; else bad "The Postgres admin login IS visible inside an app container"; fi
  fi

  local pg flags
  pg=$(docker ps --format '{{.Names}}' | grep -E '^app-postgres-[0-9]+$' | head -1 || true)
  if [ -z "$pg" ]; then
    skp "Postgres is not running (database user not checked)"
  else
    flags=$(docker exec "$pg" psql -U app -d app -tAc "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls FROM pg_roles WHERE rolname = 'app_rt'" 2>/dev/null | tr -d '[:space:]')
    case "$flags" in
      f) ok "The app's database user (app_rt) is not powerful" ;;
      t) bad "The app's database user (app_rt) has admin rights" ;;
      *) bad "The limited database user app_rt does not exist (run: ./deploy.sh db-roles)" ;;
    esac
    local ddl
    ddl=$(docker exec "$pg" psql -U app -d app -tAc "SELECT has_schema_privilege('app_rt','public','CREATE')" 2>/dev/null | tr -d '[:space:]')
    if [ "$ddl" = f ]; then
      ok "app_rt cannot create tables"
    elif [ "$ddl" = t ]; then
      bad "app_rt can create tables"
    fi
  fi
}

# --- backups ------------------------------------------------------------------------------------------------

check_backups() {
  section "Backups"
  local cron=""
  if have crontab; then cron=$(crontab -l -u deploy 2>/dev/null || true); fi
  if grep -q 'backup.sh' <<<"$cron"; then
    ok "The nightly backup is scheduled (cron, user deploy)"
  elif have crontab; then
    bad "No backup job in the cron table of the deploy user (server-setup.md, step 12)"
  else
    skp "crontab is not available"
  fi
  local log="$APP/backup.log" age
  if [ -f "$log" ]; then
    age=$(($(date +%s) - $(stat -c %Y "$log")))
    if [ "$age" -lt $((36 * 3600)) ]; then ok "The backup log was written in the last 36 hours"; else meh "The backup log is $((age / 3600)) hours old: did the backup stop?"; fi
    if tail -n 20 "$log" | grep -q 'BACKUP FAILED'; then bad "The last backup run reports a failure (see /opt/app/backup.log)"; fi
  else
    meh "There is no /opt/app/backup.log yet (no backup has run)"
  fi
}

# --- the public website -------------------------------------------------------------------------------------

check_website() {
  section "Public website"
  local domain headers
  domain=$(env_value DOMAIN)
  if [ -z "$domain" ] || ! have curl; then
    skp "No DOMAIN in .env, or curl is missing (website not checked)"
    return
  fi
  if ! headers=$(curl -sS -I -m 15 "https://$domain/" 2>/dev/null); then
    skp "https://$domain did not answer (DNS, first deploy, or no internet from here)"
    return
  fi
  local h
  for h in strict-transport-security content-security-policy x-content-type-options referrer-policy; do
    if grep -qi "^$h:" <<<"$headers"; then ok "https://$domain sends $h"; else bad "https://$domain does not send $h"; fi
  done
  if grep -qiE '^(server|x-powered-by):.*(next|express|uvicorn)' <<<"$headers"; then meh "The site tells visitors which software runs it (X-Powered-By / Server)"; fi
  local redirect
  redirect=$(curl -sS -o /dev/null -m 15 -w '%{http_code} %{redirect_url}' "http://$domain/" 2>/dev/null || true)
  case "$redirect" in 30[1278]\ https://*) ok "http:// redirects to https://" ;; *) meh "http://$domain does not redirect to https:// (answer: ${redirect:-none})" ;; esac
  if have openssl; then
    local end days
    end=$(echo | openssl s_client -servername "$domain" -connect "$domain:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
    if [ -n "$end" ]; then
      days=$((($(date -d "$end" +%s) - $(date +%s)) / 86400))
      if [ "$days" -ge 14 ]; then ok "The certificate is valid for $days more days"; else bad "The certificate ends in $days days (Caddy renews it by itself: look at ./deploy.sh logs caddy)"; fi
    fi
  fi
}

check_ssh
check_network
check_host
check_files
check_docker
check_backups
check_website

section "Things this script cannot see (check them by hand, GitHub and Hetzner websites)"
cat <<'EOF'
  [ ] GitHub: two-factor login on for your account
  [ ] GitHub: branch protection on main; environment "production" only for main (server-setup.md, step 11)
  [ ] GitHub: no deploy key or token in repository (non-environment) secrets
  [ ] Hetzner: two-factor login on; firewall my-app-fw has only 22, 80, 443 (tcp) and 443 (udp)
  [ ] Backup bucket: versioning or object lock on, if your storage offers it
  [ ] Password manager holds: .env, secrets/postgres_admin_password, .env.backup (passphrase!), SSH keys
  [ ] Calendar: monthly "run this audit + docker update", every 3 months "restore test", every 6 months "rotate secrets"
EOF

printf '\n%d passed, %d warnings, %d failed, %d skipped\n' "$pass" "$warn" "$fail" "$skip"
[ "$fail" = 0 ]
