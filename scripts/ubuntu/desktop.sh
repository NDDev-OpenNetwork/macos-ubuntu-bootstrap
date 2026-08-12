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
#   3. Google Chrome: install from Google's fingerprint-verified apt source.
#   4. RustDesk: install the pinned official package.
#   5. Firefox: remove the stock snap+apt Firefox completely.
#
# Server profile (headless) skips this entirely.
# ------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# shellcheck source=../lib/common.sh
. "$SCRIPT_DIR/../lib/common.sh"

CHROME_KEY_URL="https://dl.google.com/linux/linux_signing_key.pub"
CHROME_KEY_FINGERPRINT="EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796"
CHROME_REPO_URI="https://dl.google.com/linux/chrome/deb/"
CHROME_MANAGED_KEYRING="/etc/apt/keyrings/rldyour-google-chrome.asc"
CHROME_MANAGED_SOURCE="/etc/apt/sources.list.d/rldyour-google-chrome.sources"
RUSTDESK_VERSION="1.4.9"
RUSTDESK_URL_X64="https://github.com/rustdesk/rustdesk/releases/download/1.4.9/rustdesk-1.4.9-x86_64.deb"
RUSTDESK_SHA256_X64="7244ba47c40e804172044bfbe659467c54ce46554c98e78c8c0406f1d612fda3"
RUSTDESK_URL_ARM64="https://github.com/rustdesk/rustdesk/releases/download/1.4.9/rustdesk-1.4.9-aarch64.deb"
RUSTDESK_SHA256_ARM64="ce62c996f14d33f3bbe3a330e953644a44bace7f05885a7953f7395d69fb49c0"

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
    rldyour::log "info" "[DRY-RUN] desktop customization: GNOME dock bottom, Russian layout, Google Chrome stable, RustDesk ${RUSTDESK_VERSION}, Firefox removal"
    return 0
  fi

  # Each step is independent: one failing step does not abort the others.
  # Steps that need sudo call nddev::_sudo_refresh first.
  info "Authenticating sudo (will be refreshed as needed)"
  sudo -v || die "sudo authentication failed — cannot continue"

  nddev::_gnome_dock_bottom || warn "GNOME dock step reported an error (continuing)"
  nddev::_russian_keyboard_layout || warn "Russian keyboard step reported an error (continuing)"
  nddev::_install_google_chrome || die "Google Chrome installation failed"
  nddev::_install_rustdesk || die "RustDesk installation failed"
  nddev::_remove_firefox || warn "Firefox removal step reported an error (continuing)"
  ok "desktop customization complete"
}

nddev::_install_rustdesk() {
  info "Installing RustDesk ${RUSTDESK_VERSION}"
  local url sha stage
  case "$(uname -m)" in
    x86_64|amd64) url="$RUSTDESK_URL_X64"; sha="$RUSTDESK_SHA256_X64" ;;
    aarch64|arm64) url="$RUSTDESK_URL_ARM64"; sha="$RUSTDESK_SHA256_ARM64" ;;
    *) warn "RustDesk has no declared package for $(uname -m)"; return 1 ;;
  esac
  if dpkg-query -W -f='${Version}' rustdesk 2>/dev/null | grep -Fq "$RUSTDESK_VERSION"; then
    ok "RustDesk already installed"
    return 0
  fi
  stage="$(mktemp -d)" || return 1
  rldyour::download_verified_file "$url" "$sha" "$stage/rustdesk.deb" || return 1
  nddev::_sudo_refresh
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "$stage/rustdesk.deb"
  dpkg-query -W -f='${Status}' rustdesk 2>/dev/null | grep -Fq 'install ok installed'
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

# ----------------------------- Google Chrome -----------------------------
nddev::_install_google_chrome() {
  info "Installing current Google Chrome stable"
  nddev::_sudo_refresh
  local stage fingerprint
  stage="$(mktemp -d)" || return 1
  curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
    "$CHROME_KEY_URL" --output "$stage/google.asc" || return 1
  fingerprint="$(gpg --show-keys --with-colons "$stage/google.asc" 2>/dev/null | awk -F: '$1 == "fpr" { print $10 }')"
  [ "$fingerprint" = "$CHROME_KEY_FINGERPRINT" ] || {
    warn "Google signing key fingerprint mismatch"
    return 1
  }
  sudo install -d -m 0755 /etc/apt/keyrings
  sudo install -m 0644 "$stage/google.asc" "$CHROME_MANAGED_KEYRING"
  printf 'Types: deb\nURIs: %s\nSuites: stable\nComponents: main\nArchitectures: amd64\nSigned-By: %s\n' \
    "$CHROME_REPO_URI" "$CHROME_MANAGED_KEYRING" | sudo tee "$CHROME_MANAGED_SOURCE" >/dev/null
  sudo apt-get update
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends google-chrome-stable
  command -v google-chrome-stable >/dev/null || return 1
  xdg-settings set default-web-browser google-chrome.desktop 2>/dev/null || true
  ok "Google Chrome stable installed"
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
