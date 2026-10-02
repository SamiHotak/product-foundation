#!/usr/bin/env bash
# Hardens a fresh Ubuntu 24.04 server. Run ONCE as root, after the `deploy` user exists and has
# its SSH keys (deploy/server-setup.md, step 5). Safe to run again later (nothing is duplicated).
#
#   scp deploy/harden-server.sh root@SERVER_IP:/root/      (from your PC)
#   ssh root@SERVER_IP 'bash /root/harden-server.sh'
#
# What it does (and nothing else):
#   1. SSH: keys only, no passwords, 3 tries, only the users root + deploy, no forwarding.
#      Refuses to lock you out: it first checks that a key exists, and it checks the result.
#   2. fail2ban: bans an address for an hour after 4 wrong SSH logins (longer when it comes back).
#   3. Automatic security updates (no automatic reboot).
#   4. Clock sync (TLS certificates and login tokens need the right time).
#   5. File rights in /opt/app: .env and .env.backup only for the deploy user.
#
# It does NOT touch the firewall (server-setup.md, step 5) or Docker. After it: ./security-audit.sh
#
# For tests only: HARDEN_ROOT=/some/dir makes it write below that directory instead of /.

set -euo pipefail

ROOT=${HARDEN_ROOT:-}
SSHD_DROPIN="$ROOT/etc/ssh/sshd_config.d/00-hardening.conf"
OLD_DROPIN="$ROOT/etc/ssh/sshd_config.d/99-hardening.conf"

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ -n "$ROOT" ] || [ "$(id -u)" = 0 ] || die "Run this as root (ssh root@SERVER_IP)."

# --- 1. SSH -------------------------------------------------------------------------------------

has_key() { grep -Eqs '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-[a-z0-9]+|sk-ssh-ed25519@openssh.com) ' "$1"; }

harden_ssh() {
  log "SSH: keys only"
  has_key "$ROOT/home/deploy/.ssh/authorized_keys" ||
    die "The deploy user has no SSH key in /home/deploy/.ssh/authorized_keys. Do step 5 of server-setup.md first. (Nothing was changed.)"
  has_key "$ROOT/root/.ssh/authorized_keys" || has_key "$ROOT/home/deploy/.ssh/authorized_keys" ||
    die "No SSH key found. Turning passwords off would lock you out. (Nothing was changed.)"

  mkdir -p "$(dirname "$SSHD_DROPIN")"
  local backup=""
  if [ -f "$SSHD_DROPIN" ]; then
    backup=$(mktemp)
    cp "$SSHD_DROPIN" "$backup"
  fi
  # The name starts with 00 on purpose: sshd uses the FIRST value it reads, and files such as
  # 50-cloud-init.conf may say "PasswordAuthentication yes". 00- is read before them.
  cat >"$SSHD_DROPIN" <<'EOF'
# Written by deploy/harden-server.sh. Change the script, not this file.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
AuthenticationMethods publickey
MaxAuthTries 3
LoginGraceTime 20
MaxSessions 4
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
PermitTunnel no
ClientAliveInterval 300
ClientAliveCountMax 2
AllowUsers root deploy
EOF
  rm -f "$OLD_DROPIN" # the name step 5 of an older server-setup.md used; it would lose against cloud-init files

  if ! sshd -t; then
    if [ -n "$backup" ]; then cp "$backup" "$SSHD_DROPIN"; else rm -f "$SSHD_DROPIN"; fi
    die "sshd rejected the configuration. It was put back as before. (sshd -t shows why.)"
  fi
  # Prove that the settings really win (not just that the file exists).
  local effective
  effective=$(sshd -T)
  for want in "passwordauthentication no" "kbdinteractiveauthentication no" "maxauthtries 3"; do
    grep -qx "$want" <<<"$effective" || {
      if [ -n "$backup" ]; then cp "$backup" "$SSHD_DROPIN"; else rm -f "$SSHD_DROPIN"; fi
      die "sshd would still use a different value than '$want' (another config file wins). Nothing was applied."
    }
  done
  systemctl reload ssh 2>/dev/null || systemctl restart ssh
  printf 'SSH is hardened. Keep THIS window open and test a new login in a second window now.\n'
}

# --- 2. fail2ban --------------------------------------------------------------------------------

harden_fail2ban() {
  log "fail2ban"
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q fail2ban python3-systemd >/dev/null
  mkdir -p "$ROOT/etc/fail2ban/jail.d"
  cat >"$ROOT/etc/fail2ban/jail.d/00-hardening.local" <<'EOF'
# Written by deploy/harden-server.sh.
[DEFAULT]
bantime = 1h
findtime = 10m
maxretry = 4
bantime.increment = true
bantime.factor = 4
bantime.maxtime = 4w
ignoreip = 127.0.0.1/8 ::1

[sshd]
enabled = true
# Ubuntu 24.04 logs SSH to the journal, not to /var/log/auth.log.
backend = systemd
EOF
  systemctl enable --now fail2ban
  fail2ban-client reload >/dev/null
  printf 'fail2ban is watching SSH. (Look: fail2ban-client status sshd)\n'
}

# --- 3. automatic security updates ----------------------------------------------------------------

harden_updates() {
  log "Automatic security updates"
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q unattended-upgrades >/dev/null
  mkdir -p "$ROOT/etc/apt/apt.conf.d"
  cat >"$ROOT/etc/apt/apt.conf.d/20auto-upgrades" <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
  cat >"$ROOT/etc/apt/apt.conf.d/52-hardening-upgrades" <<'EOF'
// Written by deploy/harden-server.sh.
// No automatic reboot: you choose a quiet moment (the audit tells you when one is needed).
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOF
  printf 'Ubuntu security updates install by themselves. Docker itself is NOT updated automatically (an update restarts all containers): do that yourself once a month.\n'
}

# --- 4. clock -----------------------------------------------------------------------------------

harden_clock() {
  log "Clock"
  timedatectl set-ntp true 2>/dev/null || printf 'Could not switch clock sync on (timedatectl). Check it by hand.\n'
}

# --- 5. file rights -------------------------------------------------------------------------------

harden_files() {
  log "Files in /opt/app"
  local app="$ROOT/opt/app"
  [ -d "$app" ] || {
    printf '/opt/app does not exist yet (before the first deploy). Run this script again afterwards.\n'
    return 0
  }
  local f
  for f in .env .env.backup; do
    if [ -f "$app/$f" ]; then
      chmod 600 "$app/$f"
      printf '%s: only its owner can read it\n' "$f"
    fi
  done
  if [ -d "$app/secrets" ]; then
    chmod 700 "$app/secrets"
    # The postgres container user must read this file, so it cannot be 600. The folder is 700, so
    # nobody except the deploy user (and root) can get to it from the server.
    [ ! -f "$app/secrets/postgres_admin_password" ] || chmod 644 "$app/secrets/postgres_admin_password"
    printf 'secrets/: closed for everybody except the deploy user\n'
  fi
}

harden_ssh
harden_fail2ban
harden_updates
harden_clock
harden_files

log "Done"
printf 'Now check the result:   bash /opt/app/security-audit.sh\n'
printf 'And in a SECOND window, make sure you can still log in before you close this one.\n'
