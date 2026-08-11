#!/usr/bin/env bash
#
# scripts/ubuntu/desktop.sh
# ------------------------------------------------------------
# Ubuntu desktop customization: GNOME shell, keyboard layouts,
# default browser, and stock-browser cleanup.
#
# Called by scripts/ubuntu/install.sh in the desktop+gui profile.
# Safe to re-run (idempotent). Prompts sudo once for the whole run.
#
# What it does (desktop profile only):
#   1. GNOME dock: move to bottom, centered, macOS-style.
#   2. Keyboard: add Russian layout with Alt+Shift toggle.
#   3. BrowserOS: install the open-source agentic browser (.deb).
#   4. Firefox: remove the stock snap+apt Firefox completely.
#
# Server profile (headless) skips this entirely.
# ------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=../lib/common.sh
# shellcheck disable=SC1091
. "$SCRIPT_DIR/../lib/common.sh"

BROWSEROS_DEB_URL="https://github.com/browseros-ai/BrowserOS/releases/download/v0.47.18/BrowserOS_v0.47.18_amd64.deb"
BROWSEROS_DEB_SHA256="bfdda9be19ab0ec69602156a5c8aba3bd163351ca89539ecfda2761596b4dc7b"
BROWSEROS_DEB_TMP="/tmp/BrowserOS.deb"

# ----------------------------- helpers -----------------------------
info() { printf '\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  \u2713 %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m  \u2717 %s\033[0m\n' "$*" >&2; exit 1; }

# Steps whose failure makes the desktop layer wrong rather than merely
# unstyled. BrowserOS is a contract-declared, SHA-256-pinned application and
# the Firefox removal is a declared policy; the dock and keyboard layout are
# cosmetic and legitimately unavailable on a session without the dash-to-dock
# extension or xkb data. Required failures make the run fail.
REQUIRED_STEPS=(browseros firefox_removal)
OPTIONAL_STEPS=(gnome_dock russian_layout)

# Populated by nddev::_record; read by the aggregate report.
declare -A STEP_STATUS=()

nddev::_record() {
  STEP_STATUS["$1"]=$2
}

nddev::_is_required() {
  local candidate
  for candidate in "${REQUIRED_STEPS[@]}"; do
    [ "$candidate" = "$1" ] && return 0
  done
  return 1
}

# Run one step, remember its outcome, and never let it abort the run. Steps
# report `skipped` for a precondition they do not own (a missing GNOME
# extension) and `failed` for work they attempted and could not finish.
nddev::_step() {
  local name=$1
  shift
  if "$@"; then
    [ -n "${STEP_STATUS[$name]:-}" ] || nddev::_record "$name" ok
  else
    nddev::_record "$name" failed
  fi
}

# ----------------------------- preflight -----------------------------
nddev::desktop_configure() {
  [[ "$(id -u)" -ne 0 ]] || die "Run as your normal user, NOT root/sudo."
  command -v gsettings >/dev/null || die "gsettings missing (needs GNOME)"
  command -v localectl >/dev/null || die "localectl missing (needs systemd)"

  if [ "${RLDYOUR_DRY_RUN:-1}" -eq 1 ]; then
    rldyour::log "info" "[DRY-RUN] desktop customization: GNOME dock bottom, Russian layout, BrowserOS install, Firefox removal"
    return 0
  fi

  # Each step is independent: one failing step does not abort the others.
  # Steps that need sudo call nddev::_sudo_refresh first.
  info "Authenticating sudo (will be refreshed as needed)"
  sudo -v || die "sudo authentication failed — cannot continue"

  nddev::_step gnome_dock nddev::_gnome_dock_bottom
  nddev::_step russian_layout nddev::_russian_keyboard_layout
  nddev::_step browseros nddev::_install_browseros
  nddev::_step firefox_removal nddev::_remove_firefox

  # Report the real outcome. Announcing "complete" unconditionally is what let
  # a half-configured desktop pass both apply and strict verification.
  local name status failed_required=0 failed_optional=0
  for name in "${REQUIRED_STEPS[@]}" "${OPTIONAL_STEPS[@]}"; do
    status=${STEP_STATUS[$name]:-missing}
    case "$status" in
      ok) ok "$name: ok" ;;
      skipped) warn "$name: skipped (precondition absent)" ;;
      *)
        if nddev::_is_required "$name"; then
          printf '\033[1;31m  ✗ %s\033[0m\n' "$name: FAILED (required)" >&2
          failed_required=$((failed_required + 1))
        else
          warn "$name: failed (optional)"
          failed_optional=$((failed_optional + 1))
        fi
        ;;
    esac
  done

  if [ "$failed_required" -gt 0 ]; then
    printf '\033[1;31m  ✗ desktop customization incomplete: %d required step(s) failed\033[0m\n' \
      "$failed_required" >&2
    return 1
  fi
  if [ "$failed_optional" -gt 0 ]; then
    warn "desktop customization complete with $failed_optional optional step(s) failed"
    return 0
  fi
  ok "desktop customization complete"
}

# Refresh sudo timestamp before a sudo-requiring step. Dies if it cannot.
nddev::_sudo_refresh() {
  if ! sudo -n true 2>/dev/null; then
    info "Refreshing sudo credentials"
    sudo -v || die "sudo authentication expired and could not be refreshed"
  fi
}

# ----------------------------- GNOME dock -----------------------------
nddev::_gnome_dock_bottom() {
  info "Configuring GNOME dock (bottom, centered, macOS-style)"
  local schema="org.gnome.shell.extensions.dash-to-dock"
  gsettings list-schemas | command grep -q "^${schema}$" \
    || { nddev::_record gnome_dock skipped; return 0; }

  gsettings set "$schema" dock-position 'BOTTOM'
  gsettings set "$schema" extend-height false
  gsettings set "$schema" dock-fixed true
  gsettings set "$schema" transparency-mode 'DYNAMIC'
  gsettings set "$schema" dash-max-icon-size 48
  ok "dock moved to bottom, centered"
}

# ----------------------------- Russian keyboard -----------------------------
nddev::_russian_keyboard_layout() {
  info "Adding Russian keyboard layout (Alt+Shift toggle)"
  [ -f /usr/share/X11/xkb/symbols/ru ] \
    || {
      warn "Russian xkb data missing — install: sudo apt install xkb-data"
      nddev::_record russian_layout skipped
      return 0
    }

  nddev::_sudo_refresh
  # System locale.
  sudo sed -i 's/^# *ru_RU\.UTF-8 UTF-8/ru_RU.UTF-8 UTF-8/' /etc/locale.gen
  sudo locale-gen >/dev/null 2>&1
  if locale -a | command grep -qi 'ru_RU.utf8'; then
    ok "ru_RU.UTF-8 generated"
  else
    warn "ru_RU.UTF-8 not found in locale -a"
    return 1
  fi

  # System X11 keymap: us,ru + Alt+Shift toggle.
  sudo localectl --no-convert set-x11-keymap us,ru pc105 , grp:alt_shift_toggle
  ok "X11 keymap set to us,ru with Alt+Shift toggle"

  # A GNOME session does not read the system X11 keymap: it reads the per-user
  # org.gnome.desktop.input-sources list, and on Wayland there is no X server
  # to read the former at all. Setting only localectl left the estate's own
  # desktop with `X11 Layout: us` while the layout that actually worked had
  # been added by hand through GNOME Settings. Append ru if it is missing and
  # preserve whatever the owner already has, including order.
  nddev::_gnome_add_russian_input_source
}

# Append ('xkb', 'ru') to the GNOME input sources without reordering or
# dropping the owner's existing entries. Idempotent: an already-present ru is
# left exactly as it is.
nddev::_gnome_add_russian_input_source() {
  local current updated
  current="$(gsettings get org.gnome.desktop.input-sources sources 2>/dev/null)" || {
    warn "GNOME input sources unavailable; the session layout was not changed"
    return 0
  }
  updated="$(python3 - "$current" <<'PY'
import ast
import sys

raw = sys.argv[1]
for prefix in ("@a(ss) ", "@a(ss)"):
    if raw.startswith(prefix):
        raw = raw[len(prefix):]
        break
values = ast.literal_eval(raw)
if not isinstance(values, list):
    raise SystemExit("input-sources is not a list")
entries = [tuple(value) for value in values]
if ("xkb", "ru") not in entries:
    entries.append(("xkb", "ru"))
if ("xkb", "us") not in entries:
    entries.insert(0, ("xkb", "us"))
print("[" + ", ".join(f"('{kind}', '{name}')" for kind, name in entries) + "]")
PY
)" || {
    warn "could not compute the GNOME input source list; leaving it unchanged"
    return 0
  }
  if [ "$updated" = "$current" ]; then
    ok "GNOME input sources already include ru"
    return 0
  fi
  gsettings set org.gnome.desktop.input-sources sources "$updated" || return 1
  ok "added ru to the GNOME input sources"
}

# ----------------------------- BrowserOS -----------------------------
nddev::_install_browseros() {
  info "Installing BrowserOS (open-source agentic browser)"
  local installed
  installed="$(dpkg-query -W -f='${Status}' browseros 2>/dev/null || true)"
  if printf '%s' "$installed" | command grep -q "install ok installed"; then
    ok "BrowserOS already installed"
    return 0
  fi

  nddev::_sudo_refresh
  info "Downloading BrowserOS .deb (versioned, SHA-256 verified)"
  rldyour::download_verified_file "$BROWSEROS_DEB_URL" "$BROWSEROS_DEB_SHA256" "$BROWSEROS_DEB_TMP" \
    || { warn "BrowserOS .deb download or SHA-256 verification failed"; return 1; }
  ok "downloaded and verified ($(du -h "$BROWSEROS_DEB_TMP" | cut -f1))"

  sudo dpkg -i "$BROWSEROS_DEB_TMP" 2>/dev/null \
    || sudo apt-get install -f -y 2>/dev/null
  rm -f "$BROWSEROS_DEB_TMP"

  # `die` here used to exit the whole script from inside a `step || warn`
  # chain, so a failed BrowserOS install silently skipped the Firefox removal
  # that runs after it -- the exact opposite of the "each step is independent"
  # contract this function claims. A step reports its own failure and returns.
  if dpkg-query -W -f='${Status}' browseros 2>/dev/null | command grep -q "install ok installed"; then
    ok "BrowserOS installed"
    return 0
  fi
  warn "BrowserOS installation failed"
  return 1
}

# ----------------------------- Firefox removal -----------------------------
nddev::_remove_firefox() {
  info "Removing Firefox (snap + apt stub)"
  nddev::_sudo_refresh
  # Snap first (Ubuntu's primary firefox is snap).
  if snap list firefox >/dev/null 2>&1; then
    sudo snap remove --purge firefox
    ok "snap firefox removed"
  else
    ok "snap firefox not present"
  fi
  # Apt transitional stub package.
  if dpkg -l firefox 2>/dev/null | command grep -q '^ii'; then
    sudo apt-get purge -y firefox
    sudo apt-get autoremove -y 2>/dev/null || true
    ok "apt firefox stub purged"
  else
    ok "apt firefox not present"
  fi
}

nddev::desktop_configure "$@"
