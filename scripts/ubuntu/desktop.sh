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
MODULE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# shellcheck source=../lib/common.sh
. "$SCRIPT_DIR/../lib/common.sh"

BROWSEROS_DEB_URL="https://github.com/browseros-ai/BrowserOS/releases/download/v0.47.18/BrowserOS_v0.47.18_amd64.deb"
BROWSEROS_DEB_SHA256="bfdda9be19ab0ec69602156a5c8aba3bd163351ca89539ecfda2761596b4dc7b"
BROWSEROS_DEB_TMP="/tmp/BrowserOS.deb"

# ----------------------------- helpers -----------------------------
info() { printf '\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  \u2713 %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m  \u2717 %s\033[0m\n' "$*" >&2; exit 1; }

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

  nddev::_gnome_dock_bottom || warn "GNOME dock step reported an error (continuing)"
  nddev::_russian_keyboard_layout || warn "Russian keyboard step reported an error (continuing)"
  nddev::_install_browseros || warn "BrowserOS install step reported an error (continuing)"
  nddev::_remove_firefox || warn "Firefox removal step reported an error (continuing)"
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
    || { warn "dash-to-dock schema not found — skipping"; return 0; }

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
    || { warn "Russian xkb data missing — install: sudo apt install xkb-data"; return 0; }

  nddev::_sudo_refresh
  # System locale.
  sudo sed -i 's/^# *ru_RU\.UTF-8 UTF-8/ru_RU.UTF-8 UTF-8/' /etc/locale.gen
  sudo locale-gen >/dev/null 2>&1
  locale -a | command grep -qi 'ru_RU.utf8' \
    && ok "ru_RU.UTF-8 generated" \
    || warn "ru_RU.UTF-8 not found in locale -a"

  # System X11 keymap: us,ru + Alt+Shift toggle.
  sudo localectl --no-convert set-x11-keymap us,ru pc105 , grp:alt_shift_toggle
  ok "X11 keymap set to us,ru with Alt+Shift toggle"
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

  dpkg-query -W -f='${Status}' browseros 2>/dev/null | command grep -q "install ok installed" \
    && ok "BrowserOS installed" \
    || die "BrowserOS installation failed"
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
