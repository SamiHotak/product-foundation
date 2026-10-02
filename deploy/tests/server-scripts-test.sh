#!/usr/bin/env bash
# shellcheck disable=SC2016  # stub bodies are single-quoted on purpose: they expand when the stub runs
# Tests the LOGIC of harden-server.sh and security-audit.sh with pretend system commands
# (sshd, ufw, ss, docker, ...). No server needed:   bash deploy/tests/server-scripts-test.sh
# It cannot prove that real sshd / fail2ban / ufw behave the same; the first run on the real
# server does that (the audit script then tells you).
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
deploy=$(cd "$here/.." && pwd)
pass=0
failures=0

check() {
  local desc=$1
  shift
  if "$@"; then
    pass=$((pass + 1))
  else
    printf 'FAIL: %s\n' "$desc"
    failures=$((failures + 1))
  fi
}
has() { grep -qF -- "$2" "$1"; }
hasnt() { ! grep -qF -- "$2" "$1"; }

stub() { # stub <name> <body...>: a command that runs the given shell code
  local name=$1
  shift
  printf '#!/usr/bin/env bash\n%s\n' "$*" >"$bin/$name"
  chmod +x "$bin/$name"
}

new_world() {
  work=$(mktemp -d)
  bin="$work/bin"
  root="$work/root"
  log="$work/calls.log"
  mkdir -p "$bin" "$root"
  : >"$log"
  export PATH="$bin:$PATH" HARDEN_ROOT="$root" AUDIT_ROOT="$root"
}

# ====================================================================== harden-server.sh

harden_world() {
  new_world
  mkdir -p "$root/home/deploy/.ssh" "$root/etc/ssh/sshd_config.d" "$root/opt/app/secrets"
  echo "ssh-ed25519 AAAAC3Nza deploy-key" >"$root/home/deploy/.ssh/authorized_keys"
  stub sshd 'case "$1" in
  -t) if [ "${FAKE_SSHD_BAD:-0}" = 1 ]; then echo "bad config" >&2; exit 1; fi; exit 0 ;;
  -T) f="$HARDEN_ROOT/etc/ssh/sshd_config.d/00-hardening.conf"
      if [ -f "$f" ]; then grep -v "^#" "$f" | tr "A-Z" "a-z"; fi | { if [ -n "${FAKE_SSHD_OVERRIDE_PASSWORD:-}" ]; then grep -v "^passwordauthentication"; echo "passwordauthentication $FAKE_SSHD_OVERRIDE_PASSWORD"; else cat; fi; }
      exit 0 ;;
esac'
  for c in systemctl apt-get fail2ban-client timedatectl; do
    stub "$c" "echo \"$c \$*\" >>\"$log\""
  done
  : >"$root/opt/app/.env"
  chmod 644 "$root/opt/app/.env"
  echo adminpw >"$root/opt/app/secrets/postgres_admin_password"
  chmod 600 "$root/opt/app/secrets/postgres_admin_password"
  chmod 755 "$root/opt/app/secrets"
  echo "PasswordAuthentication yes" >"$root/etc/ssh/sshd_config.d/99-hardening.conf"
}
run_harden() { bash "$deploy/harden-server.sh" >"$work/out.log" 2>&1; }
dropin() { echo "$root/etc/ssh/sshd_config.d/00-hardening.conf"; }

harden_world
check "harden: succeeds on a prepared server" run_harden
check "harden: passwords are off" has "$(dropin)" "PasswordAuthentication no"
check "harden: only publickey" has "$(dropin)" "AuthenticationMethods publickey"
check "harden: 3 tries" has "$(dropin)" "MaxAuthTries 3"
check "harden: only root and deploy may log in" has "$(dropin)" "AllowUsers root deploy"
check "harden: no TCP forwarding" has "$(dropin)" "AllowTcpForwarding no"
check "harden: the old 99- file is removed (it would lose against cloud-init)" test ! -e "$root/etc/ssh/sshd_config.d/99-hardening.conf"
check "harden: sshd was reloaded" has "$log" "systemctl reload ssh"
check "harden: fail2ban jail reads the journal" has "$root/etc/fail2ban/jail.d/00-hardening.local" "backend = systemd"
check "harden: fail2ban bans after 4 tries" has "$root/etc/fail2ban/jail.d/00-hardening.local" "maxretry = 4"
check "harden: fail2ban was started and reloaded" has "$log" "fail2ban-client reload"
check "harden: automatic updates are on" has "$root/etc/apt/apt.conf.d/20auto-upgrades" 'Unattended-Upgrade "1"'
check "harden: but no automatic reboot" has "$root/etc/apt/apt.conf.d/52-hardening-upgrades" 'Automatic-Reboot "false"'
check "harden: clock sync switched on" has "$log" "timedatectl set-ntp true"
check "harden: .env is 600" test "$(stat -c %a "$root/opt/app/.env")" = 600
check "harden: secrets dir is 700" test "$(stat -c %a "$root/opt/app/secrets")" = 700
check "harden: the admin password file is readable by the container" test "$(stat -c %a "$root/opt/app/secrets/postgres_admin_password")" = 644
before=$(cat "$(dropin)")
check "harden: running it twice works" run_harden
check "harden: and changes nothing" test "$(cat "$(dropin)")" = "$before"
check "harden: and there is still exactly one drop-in" test "$(find "$root/etc/ssh/sshd_config.d" -type f | wc -l)" = 1

harden_world
rm "$root/home/deploy/.ssh/authorized_keys"
check "harden: refuses when the deploy user has no key" bash -c "! bash '$deploy/harden-server.sh' >'$work/out.log' 2>&1"
check "harden: no key -> it says why" has "$work/out.log" "no SSH key"
check "harden: no key -> nothing was written" test ! -e "$(dropin)"
check "harden: no key -> sshd was not touched" hasnt "$log" "systemctl"

harden_world
export FAKE_SSHD_BAD=1
check "harden: refuses a config that sshd rejects" bash -c "! bash '$deploy/harden-server.sh' >'$work/out.log' 2>&1"
unset FAKE_SSHD_BAD
check "harden: a rejected config is removed again" test ! -e "$(dropin)"
check "harden: a rejected config is never loaded" hasnt "$log" "systemctl reload ssh"

harden_world
echo "MaxAuthTries 6" >"$(dropin)"
cp "$(dropin)" "$work/previous"
export FAKE_SSHD_BAD=1
bash "$deploy/harden-server.sh" >"$work/out.log" 2>&1 || true
unset FAKE_SSHD_BAD
check "harden: a previous drop-in is put back when the new one is rejected" test "$(cat "$(dropin)")" = "$(cat "$work/previous")"

harden_world
export FAKE_SSHD_OVERRIDE_PASSWORD=yes
check "harden: refuses when another file would still allow passwords" bash -c "! bash '$deploy/harden-server.sh' >'$work/out.log' 2>&1"
unset FAKE_SSHD_OVERRIDE_PASSWORD
check "harden: it names the setting" has "$work/out.log" "passwordauthentication no"
check "harden: the ineffective drop-in is removed" test ! -e "$(dropin)"
check "harden: nothing was reloaded" hasnt "$log" "systemctl reload ssh"

# ====================================================================== security-audit.sh

GOOD_SSH='passwordauthentication no
kbdinteractiveauthentication no
permitrootlogin prohibit-password
maxauthtries 3
x11forwarding no'

audit_world() {
  new_world
  mkdir -p "$root/opt/app/secrets" "$root/var/run"
  printf 'DOMAIN=example.com\nDEMO_ENABLED=false\nSECRET_KEY=abc\n' >"$root/opt/app/.env"
  : >"$root/opt/app/.env.backup"
  echo "0123456789abcdef0123456789abcdef0123456789abcdef" >"$root/opt/app/secrets/postgres_admin_password"
  chmod 600 "$root/opt/app/.env" "$root/opt/app/.env.backup"
  chmod 700 "$root/opt/app/secrets"
  chmod 644 "$root/opt/app/secrets/postgres_admin_password"
  echo "Backup done: db-x (5 KB)" >"$root/opt/app/backup.log"
  stub sshd 'echo "$FAKE_SSHD"'
  export FAKE_SSHD="$GOOD_SSH"
  stub ufw 'printf "Status: active\nDefault: deny (incoming), allow (outgoing), disabled (routed)\n"'
  stub ss 'printf "tcp LISTEN 0 4096 0.0.0.0:22 0.0.0.0:*\ntcp LISTEN 0 4096 0.0.0.0:80 0.0.0.0:*\ntcp LISTEN 0 4096 [::]:443 [::]:*\ntcp LISTEN 0 4096 127.0.0.54:53 0.0.0.0:*\nudp UNCONN 0 0 0.0.0.0:443 0.0.0.0:*\n%s" "${FAKE_SS_EXTRA:-}"'
  stub systemctl 'if [ "$1" = is-active ]; then echo "${FAKE_F2B:-active}"; fi'
  stub fail2ban-client 'exit 0'
  stub apt-config 'echo "${FAKE_APT:-APT::Periodic::Unattended-Upgrade \"1\";}"'
  stub timedatectl 'echo yes'
  stub crontab 'echo "${FAKE_CRON-30 2 * * * cd /opt/app && ./backup.sh}"'
  stub curl 'case "$*" in
  *"-I"*) printf "HTTP/2 200\r\nstrict-transport-security: max-age=1\r\ncontent-security-policy: default-src self\r\nx-content-type-options: nosniff\r\nreferrer-policy: same-origin\r\n" ;;
  *"-w"*) printf "308 https://example.com/" ;;
esac'
  stub openssl 'case "$1" in s_client) echo cert ;; x509) echo "notAfter=${FAKE_CERT_END:-Dec 31 00:00:00 2099 GMT}" ;; esac'
  # docker: names, published ports, inspect, env, psql
  stub docker 'case "$*" in
  "ps") exit 0 ;;
  *"--format {{.Names}} {{.Ports}}"*) printf "app-caddy-1 0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp, :::443->443/tcp\napp-postgres-1 5432/tcp\n%s" "${FAKE_DOCKER_PORTS:-}" ;;
  *"--format {{.Names}}"*) printf "app-caddy-1\napp-backend-1\napp-worker-1\napp-postgres-1\n" ;;
  *"inspect -f {{.HostConfig.CapDrop}}"*) echo "${FAKE_CAPS:-[ALL] [no-new-privileges:true]}" ;;
  *"inspect -f {{.HostConfig.SecurityOpt}}"*) echo "[no-new-privileges:true]" ;;
  *"printenv"*) printf "APP_URL=https://example.com\nDATABASE_URL=postgresql://app_rt:x@postgres/app\n"; [ "${FAKE_LEAK:-0}" = 1 ] && echo "POSTGRES_PASSWORD=0123456789abcdef0123456789abcdef0123456789abcdef"; true ;;
  *"rolsuper OR"*) echo "${FAKE_RT_POWER:-f}" ;;
  *"has_schema_privilege"*) echo "${FAKE_RT_CREATE:-f}" ;;
esac'
}
run_audit() { bash "$deploy/security-audit.sh" >"$work/out.log" 2>&1; }

audit_world
check "audit: a healthy server passes (exit 0)" run_audit
check "audit: no FAIL lines on a healthy server" hasnt "$work/out.log" "FAIL "
check "audit: it reports the SSH password setting" has "$work/out.log" "PASS  SSH passwords are off"
check "audit: it checks the limited database user" has "$work/out.log" "PASS  The app's database user (app_rt) is not powerful"
check "audit: it checks the admin login is not in app containers" has "$work/out.log" "PASS  The Postgres admin login is not visible inside the app containers"
check "audit: it lists what it cannot see" has "$work/out.log" "Things this script cannot see"
check "audit: the summary is printed" has "$work/out.log" "0 failed"

audit_world
export FAKE_SSHD="${GOOD_SSH/passwordauthentication no/passwordauthentication yes}"
check "audit: SSH passwords on -> fails" bash -c "! bash '$deploy/security-audit.sh' >'$work/out.log' 2>&1"
check "audit: ... and says so" has "$work/out.log" "FAIL  SSH passwords are off (is: yes)"

audit_world
printf 'Status: inactive\n' >/dev/null
stub ufw 'printf "Status: inactive\n"'
export FAKE_SS_EXTRA='tcp LISTEN 0 4096 0.0.0.0:5432 0.0.0.0:*
'
export FAKE_F2B=inactive
export FAKE_APT='APT::Periodic::Unattended-Upgrade "0";'
export FAKE_CRON=''
check "audit: a badly configured server fails" bash -c "! bash '$deploy/security-audit.sh' >'$work/out.log' 2>&1"
check "audit: inactive firewall" has "$work/out.log" "FAIL  ufw is not active"
check "audit: an open database port" has "$work/out.log" "FAIL  Unexpected TCP ports listen to the internet: 0.0.0.0:5432"
check "audit: fail2ban down" has "$work/out.log" "FAIL  fail2ban is not running"
check "audit: updates off" has "$work/out.log" "FAIL  Automatic security updates are off"
check "audit: no backup job" has "$work/out.log" "FAIL  No backup job"
unset FAKE_SS_EXTRA FAKE_F2B FAKE_APT FAKE_CRON

audit_world
echo "export POSTGRES_PASSWORD=0123456789abcdef0123456789abcdef0123456789abcdef" >>"$root/opt/app/.env"
check "audit: 'export POSTGRES_PASSWORD=' is found too" bash -c "! bash '$deploy/security-audit.sh' >'$work/out.log' 2>&1"
check "audit: ... and named" has "$work/out.log" "FAIL  POSTGRES_PASSWORD is in .env"

audit_world
chmod 644 "$root/opt/app/.env"
chmod 755 "$root/opt/app/secrets"
echo "POSTGRES_PASSWORD=0123456789abcdef0123456789abcdef0123456789abcdef" >>"$root/opt/app/.env"
export FAKE_LEAK=1 FAKE_RT_POWER=t FAKE_RT_CREATE=t FAKE_DOCKER_PORTS='app-redis-1 0.0.0.0:6379->6379/tcp
'
check "audit: leaky secrets fail" bash -c "! bash '$deploy/security-audit.sh' >'$work/out.log' 2>&1"
check "audit: .env readable by others" has "$work/out.log" "FAIL  .env has mode 644"
check "audit: secrets dir open" has "$work/out.log" "FAIL  secrets/ has mode 755"
check "audit: admin login in .env" has "$work/out.log" "FAIL  POSTGRES_PASSWORD is in .env"
check "audit: admin login inside a container" has "$work/out.log" "FAIL  The Postgres admin login IS visible inside an app container"
check "audit: powerful app database user" has "$work/out.log" "FAIL  The app's database user (app_rt) has admin rights"
check "audit: app user can create tables" has "$work/out.log" "FAIL  app_rt can create tables"
check "audit: a published Redis port" has "$work/out.log" "FAIL  Containers publish other ports to the internet: 6379"
check "audit: the secret value itself is never printed" hasnt "$work/out.log" "0123456789abcdef0123456789abcdef"
unset FAKE_LEAK FAKE_RT_POWER FAKE_RT_CREATE FAKE_DOCKER_PORTS

audit_world
touch "$root/var/run/reboot-required"
export FAKE_CERT_END="Jan 1 00:00:00 2020 GMT"
check "audit: an expired certificate fails" bash -c "! bash '$deploy/security-audit.sh' >'$work/out.log' 2>&1"
check "audit: the pending reboot is only a warning" has "$work/out.log" "WARN  A reboot is needed"
unset FAKE_CERT_END

audit_world
stub docker 'exit 1'; stub ss 'exit 1'
check "audit: missing tools are skipped, not failed" run_audit
check "audit: Docker skipped" has "$work/out.log" "SKIP  Docker is not reachable"

audit_world
rm "$root/opt/app/secrets/postgres_admin_password"
check "audit: a missing admin password file fails" bash -c "! bash '$deploy/security-audit.sh' >'$work/out.log' 2>&1"

printf '\n%d checks passed, %d failed\n' "$pass" "$failures"
[ "$failures" = 0 ]
