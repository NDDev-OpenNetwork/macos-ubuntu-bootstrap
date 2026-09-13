#!/usr/bin/env bash
# Provision and verify the loopback-only XRDP layer used by desktop-server.
# The bootstrap owns configuration, not credentials: the desktop account and
# its password must already exist and SSH authentication remains owner-managed.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
# shellcheck disable=SC1091
source "$SCRIPT_DIR/../lib/common.sh"
# shellcheck source=privilege.sh
# shellcheck disable=SC1091
source "$SCRIPT_DIR/privilege.sh"

readonly RLDYOUR_RDP_STATE=/var/lib/rldyour-bootstrap/remote-desktop
readonly RLDYOUR_RDP_PORT=3389

rldyour::remote_desktop::usage() {
  cat <<'EOF'
Usage: scripts/ubuntu/remote-desktop.sh [--plan|--apply|--verify] [--user USER]

Configure a pre-existing non-root account for a persistent Ubuntu GNOME XRDP
session. XRDP binds to 127.0.0.1:3389 and is reachable only through an
owner-managed SSH local forward. The script never creates or reads passwords.
EOF
}

rldyour::remote_desktop::supported_host() {
  [ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ] && [ -r /etc/os-release ] || return 1
  (
    # Ubuntu 26.04 removed the Xorg GNOME session this XRDP composition uses.
    # shellcheck disable=SC1091
    source /etc/os-release
    [ "${ID:-}" = ubuntu ] && [ "${VERSION_ID:-}" = 24.04 ]
  )
}

rldyour::remote_desktop::validate_user() {
  local user=$1 record uid home shell
  [[ "$user" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || return 1
  record="$(getent passwd "$user")" || return 1
  IFS=: read -r _ _ uid _ _ home shell <<<"$record"
  [ "$uid" -ge 1000 ] && [ "$uid" -lt 60000 ] || return 1
  [ "$home" = "/home/$user" ] && [ -d "$home" ] && [ ! -L "$home" ] || return 1
  case "$shell" in /usr/sbin/nologin|/bin/false) return 1 ;; esac
}

rldyour::remote_desktop::managed_user_file() {
  local user=$1 destination=$2 mode=$3 marker=$4 source=$5
  local home group
  home="$(getent passwd "$user" | cut -d: -f6)"
  group="$(id -gn "$user")"
  case "$destination" in "$home"/*) ;; *) return 1 ;; esac
  if [ -e "$destination" ] || [ -L "$destination" ]; then
    [ ! -L "$destination" ] && [ -f "$destination" ] || return 1
    grep -Fqx "$marker" "$destination" || {
      rldyour::log "error" "unmanaged remote-desktop file exists; preserved: $destination"
      return 1
    }
    cmp -s "$source" "$destination" || {
      rldyour::log "error" "managed remote-desktop file diverged; preserved: $destination"
      return 1
    }
    return 0
  fi
  install -d -o "$user" -g "$group" -m 0700 "$(dirname "$destination")"
  install -o "$user" -g "$group" -m "$mode" "$source" "$destination"
}

rldyour::remote_desktop::configure_ini() {
  local path=$1 section=$2
  shift 2
  # python-surface: remote-desktop-ini
  /usr/bin/python3 -I - "$path" "$section" "$@" <<'PY'
import os
import pathlib
import stat
import sys
import tempfile

path = pathlib.Path(sys.argv[1])
section = sys.argv[2]
pairs = dict(value.split("=", 1) for value in sys.argv[3:])
st = path.lstat()
if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
    raise SystemExit(f"unsafe configuration target: {path}")
lines = path.read_text(encoding="utf-8").splitlines()
headers = [line.strip()[1:-1] for line in lines if line.strip().startswith("[") and line.strip().endswith("]")]
if headers.count(section) != 1:
    raise SystemExit(f"expected exactly one [{section}] in {path}")
current = None
seen = set()
output = []
for line in lines:
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        if current == section:
            output.extend(f"{key}={value}" for key, value in pairs.items() if key not in seen)
        current = stripped[1:-1]
    key = line.split("=", 1)[0].strip() if "=" in line and not stripped.startswith(("#", ";")) else ""
    if current == section and key in pairs:
        if key in seen:
            raise SystemExit(f"duplicate managed key {key} in {path}")
        output.append(f"{key}={pairs[key]}")
        seen.add(key)
    else:
        output.append(line)
if current == section:
    output.extend(f"{key}={value}" for key, value in pairs.items() if key not in seen)
payload = ("\n".join(output) + "\n").encode()
fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
try:
    os.write(fd, payload)
    os.fchmod(fd, stat.S_IMODE(st.st_mode))
    os.fchown(fd, st.st_uid, st.st_gid)
    os.fsync(fd)
    os.close(fd)
    fd = -1
    os.replace(temporary, path)
finally:
    if fd >= 0:
        os.close(fd)
    try: os.unlink(temporary)
    except FileNotFoundError: pass
PY
}

rldyour::remote_desktop::root_apply() {
  local user=$1 home hostname_value tmp leaf mode
  [ "$EUID" -eq 0 ] || return 1
  rldyour::remote_desktop::supported_host || {
    rldyour::log "error" "desktop-server RDP supports Ubuntu 24.04 amd64 only"
    return 2
  }
  rldyour::remote_desktop::validate_user "$user" || {
    rldyour::log "error" "RDP user must be an existing non-root login account under /home"
    return 2
  }
  home="$(getent passwd "$user" | cut -d: -f6)"
  hostname_value="$(hostname -s | tr -cd 'A-Za-z0-9.-')"
  [ -n "$hostname_value" ] || hostname_value=ubuntu-desktop-server
  export DEBIAN_FRONTEND=noninteractive

  apt-get update
  apt-get install -o DPkg::Lock::Timeout=120 -y --no-install-recommends --no-upgrade \
    ubuntu-desktop-minimal xrdp xorgxrdp dbus-x11 dbus-user-session \
    gnome-terminal mesa-utils language-pack-ru openssh-server

  install -d -o root -g root -m 0700 "$RLDYOUR_RDP_STATE/backups"
  for path in /etc/xrdp/xrdp.ini /etc/xrdp/sesman.ini; do
    [ -f "$path" ] && [ ! -L "$path" ] || return 1
    if [ ! -e "$RLDYOUR_RDP_STATE/backups/${path##*/}.vendor" ]; then
      install -o root -g root -m 0600 "$path" "$RLDYOUR_RDP_STATE/backups/${path##*/}.vendor"
    fi
  done

  install -d -o root -g xrdp -m 0750 /etc/xrdp/tls
  if [ ! -s /etc/xrdp/tls/server.key ] || [ ! -s /etc/xrdp/tls/server.crt ]; then
    if [ -e /etc/xrdp/tls/server.key ] || [ -e /etc/xrdp/tls/server.crt ]; then
      rldyour::log "error" "partial XRDP TLS identity exists; preserved"
      return 1
    fi
    openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 730 \
      -subj "/CN=${hostname_value}" \
      -addext "subjectAltName=DNS:${hostname_value},IP:127.0.0.1" \
      -keyout /etc/xrdp/tls/server.key -out /etc/xrdp/tls/server.crt
  fi
  chown root:xrdp /etc/xrdp/tls/server.key /etc/xrdp/tls/server.crt
  chmod 0640 /etc/xrdp/tls/server.key
  chmod 0644 /etc/xrdp/tls/server.crt
  openssl x509 -in /etc/xrdp/tls/server.crt -noout -checkend 604800 >/dev/null || {
    rldyour::log "error" "XRDP TLS certificate is invalid or expires within seven days"
    return 1
  }

  rldyour::remote_desktop::configure_ini /etc/xrdp/xrdp.ini Globals \
    "port=tcp://127.0.0.1:${RLDYOUR_RDP_PORT}" "security_layer=tls" \
    "crypt_level=high" "certificate=/etc/xrdp/tls/server.crt" \
    "key_file=/etc/xrdp/tls/server.key" "ssl_protocols=TLSv1.2, TLSv1.3" \
    "max_bpp=32" "autorun=Xorg"
  rldyour::remote_desktop::configure_ini /etc/xrdp/sesman.ini Security \
    "AllowRootLogin=false" "MaxLoginRetry=4"
  rldyour::remote_desktop::configure_ini /etc/xrdp/sesman.ini Sessions \
    "MaxSessions=2" "KillDisconnected=false" "DisconnectedTimeLimit=0" \
    "IdleTimeLimit=0" "Policy=Default"

  tmp="$(mktemp -d)"
  trap 'rm -rf -- "$tmp"' RETURN
  cat >"$tmp/xsessionrc" <<'EOF'
# Managed by macos-ubuntu-bootstrap: desktop-server-xsession-v1
export DESKTOP_SESSION=ubuntu
export GNOME_SHELL_SESSION_MODE=ubuntu
export XDG_CURRENT_DESKTOP=ubuntu:GNOME
export XDG_SESSION_TYPE=x11
export XDG_CONFIG_DIRS=/etc/xdg/xdg-ubuntu:/etc/xdg
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
if [ -S "$XDG_RUNTIME_DIR/bus" ]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
fi
EOF
  cat >"$tmp/xsession" <<'EOF'
#!/bin/sh
# Managed by macos-ubuntu-bootstrap: desktop-server-xsession-v1
dbus-update-activation-environment --systemd DISPLAY XAUTHORITY \
  XDG_CURRENT_DESKTOP XDG_SESSION_TYPE GNOME_SHELL_SESSION_MODE \
  DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR
exec gnome-session --session=ubuntu
EOF
  # Adopt only the byte-exact predecessor used by the Amsterdam desktop. This
  # makes the existing proven deployment migratable without treating an
  # arbitrary owner file as ours. The original remains in the root-only state
  # backup before the managed marker is introduced.
  cat >"$tmp/xsessionrc.legacy-amsterdam-v1" <<'EOF'
export DESKTOP_SESSION=ubuntu
export GNOME_SHELL_SESSION_MODE=ubuntu
export XDG_CURRENT_DESKTOP=ubuntu:GNOME
export XDG_SESSION_TYPE=x11
export XDG_CONFIG_DIRS=/etc/xdg/xdg-ubuntu:/etc/xdg
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
if [ -S "$XDG_RUNTIME_DIR/bus" ]; then
    export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
fi
EOF
  cat >"$tmp/xsession.legacy-amsterdam-v1" <<'EOF'
#!/bin/sh
dbus-update-activation-environment --systemd DISPLAY XAUTHORITY \
    XDG_CURRENT_DESKTOP XDG_SESSION_TYPE GNOME_SHELL_SESSION_MODE \
    DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR
exec gnome-session --session=ubuntu
EOF
  for leaf in xsessionrc xsession; do
    if [ -f "$home/.${leaf}" ] && [ ! -L "$home/.${leaf}" ] &&
      cmp -s "$tmp/${leaf}.legacy-amsterdam-v1" "$home/.${leaf}"; then
      install -o root -g root -m 0600 "$home/.${leaf}" \
        "$RLDYOUR_RDP_STATE/backups/${user}.${leaf}.legacy-amsterdam-v1"
      if [ "$leaf" = xsession ]; then mode=0755; else mode=0644; fi
      install -o "$user" -g "$(id -gn "$user")" -m "$mode" "$tmp/$leaf" "$home/.$leaf"
    fi
  done
  rldyour::remote_desktop::managed_user_file "$user" "$home/.xsessionrc" 0644 \
    '# Managed by macos-ubuntu-bootstrap: desktop-server-xsession-v1' "$tmp/xsessionrc"
  rldyour::remote_desktop::managed_user_file "$user" "$home/.xsession" 0755 \
    '# Managed by macos-ubuntu-bootstrap: desktop-server-xsession-v1' "$tmp/xsession"

  install -d -o root -g root -m 0755 /etc/systemd/system/xrdp.service.d \
    /etc/systemd/system/xrdp-sesman.service.d
  for unit in xrdp xrdp-sesman; do
    cat >"$tmp/${unit}.conf" <<'EOF'
# Managed by macos-ubuntu-bootstrap: desktop-server-recovery-v1
[Service]
Restart=on-failure
RestartSec=5s
EOF
    install -o root -g root -m 0644 "$tmp/${unit}.conf" \
      "/etc/systemd/system/${unit}.service.d/50-rldyour-recovery.conf"
  done

  systemctl disable --now gdm3.service 2>/dev/null || true
  systemctl --global mask gnome-remote-desktop.service
  systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
  systemctl set-default multi-user.target
  systemctl daemon-reload
  systemctl enable --now ssh.service xrdp.service xrdp-sesman.service
  systemctl restart xrdp.service
  rldyour::remote_desktop::verify "$user"
}

rldyour::remote_desktop::verify() {
  local user=$1 package listeners address
  rldyour::remote_desktop::supported_host || return 1
  rldyour::remote_desktop::validate_user "$user" || return 1
  for package in ubuntu-desktop-minimal xrdp xorgxrdp; do
    [ "$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null)" = 'install ok installed' ] || return 1
  done
  systemctl is-active --quiet ssh.service
  systemctl is-active --quiet xrdp.service
  systemctl is-active --quiet xrdp-sesman.service
  grep -Fxq "port=tcp://127.0.0.1:${RLDYOUR_RDP_PORT}" /etc/xrdp/xrdp.ini
  grep -Fxq 'security_layer=tls' /etc/xrdp/xrdp.ini
  grep -Fxq 'AllowRootLogin=false' /etc/xrdp/sesman.ini
  case "$(systemctl --global is-enabled gnome-remote-desktop.service 2>/dev/null || true)" in
    masked|disabled) ;;
    *) return 1 ;;
  esac
  listeners="$(ss -H -lnt "( sport = :${RLDYOUR_RDP_PORT} )" | awk '{print $4}')"
  [ -n "$listeners" ] || return 1
  while IFS= read -r address; do
    [ "$address" = "127.0.0.1:${RLDYOUR_RDP_PORT}" ] || return 1
  done <<<"$listeners"
  [ "$(systemctl get-default)" = multi-user.target ]
  rldyour::log "ok" "desktop-server RDP is active on loopback only"
}

rldyour::remote_desktop::main() {
  local mode=plan user=${RLDYOUR_REMOTE_DESKTOP_USER:-$(id -un)}
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --plan) mode=plan; shift ;;
      --apply) mode=apply; shift ;;
      --verify) mode=verify; shift ;;
      --root-apply) mode=root-apply; shift ;;
      --user) user=${2:?--user requires an account}; shift 2 ;;
      -h|--help) rldyour::remote_desktop::usage; return 0 ;;
      *) rldyour::log "error" "unknown remote-desktop argument: $1"; return 2 ;;
    esac
  done
  if [ "$mode" = plan ]; then
    [[ "$user" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || {
      rldyour::log "error" "invalid planned RDP user"
      return 2
    }
  else
    rldyour::remote_desktop::supported_host || {
      rldyour::log "error" "desktop-server RDP supports Ubuntu 24.04 amd64 only"
      return 2
    }
    rldyour::remote_desktop::validate_user "$user" || {
      rldyour::log "error" "RDP user must be an existing non-root login account under /home"
      return 2
    }
  fi
  case "$mode" in
    plan)
      rldyour::log "info" "[DRY-RUN] configure XRDP for $user on 127.0.0.1:${RLDYOUR_RDP_PORT}; preserve credentials; require an SSH tunnel"
      ;;
    apply)
      [ "$EUID" -ne 0 ] || { rldyour::log "error" "run the bootstrap as the desktop user, not root"; return 2; }
      rldyour::privilege::root_exec bash "$SCRIPT_DIR/remote-desktop.sh" --root-apply --user "$user"
      ;;
    verify)
      rldyour::remote_desktop::verify "$user"
      ;;
    root-apply)
      rldyour::remote_desktop::root_apply "$user"
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  # Internal root entrypoint is deliberately not advertised in usage.
  if [ "${1:-}" = --root-apply ]; then
    rldyour::remote_desktop::main "$@"
  else
    rldyour::remote_desktop::main "$@"
  fi
fi
