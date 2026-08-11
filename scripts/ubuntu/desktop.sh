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
#   3. Pinned .deb applications: BrowserOS and RustDesk.
#   4. Google Chrome: install from the fingerprint-verified signed apt source.
#   5. Firefox: remove the stock snap+apt Firefox completely.
#
# Server profile (headless) skips this entirely.
# ------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=../lib/common.sh
# shellcheck disable=SC1091
. "$SCRIPT_DIR/../lib/common.sh"

# Desktop applications upstream publishes only as a .deb. One row per
# application, one generic installer: BrowserOS and RustDesk have exactly the
# same shape, and a second bespoke install path is how one of them quietly
# stops being verified.
#
# Row format (semicolon-separated, no spaces inside a field):
#   name;package;url_x64;sha256_x64;url_arm64;sha256_arm64
#
# An empty arm64 pair means upstream publishes no arm64 build; the step reports
# `skipped` on that architecture rather than failing a device that cannot have
# the application at all. Every digest below was confirmed by downloading the
# artifact, not copied from a release note.
DESKTOP_DEBS=(
  "browseros;browseros;https://github.com/browseros-ai/BrowserOS/releases/download/v0.47.18/BrowserOS_v0.47.18_amd64.deb;bfdda9be19ab0ec69602156a5c8aba3bd163351ca89539ecfda2761596b4dc7b;;"
  "rustdesk;rustdesk;https://github.com/rustdesk/rustdesk/releases/download/1.4.9/rustdesk-1.4.9-x86_64.deb;7244ba47c40e804172044bfbe659467c54ce46554c98e78c8c0406f1d612fda3;https://github.com/rustdesk/rustdesk/releases/download/1.4.9/rustdesk-1.4.9-aarch64.deb;ce62c996f14d33f3bbe3a330e953644a44bace7f05885a7953f7395d69fb49c0"
)

# Google Chrome. Deliberately NOT pinned to a SHA-256: pinning a browser to an
# old build is a security liability, not a reproducibility gain, so the supply
# chain is controlled by the signing key instead. This primary fingerprint was
# confirmed against two independent sources -- the published
# dl.google.com/linux/linux_signing_key.pub and the key embedded in the
# package's own /etc/cron.daily/google-chrome.
CHROME_KEY_URL="https://dl.google.com/linux/linux_signing_key.pub"
CHROME_KEY_FINGERPRINT="EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796"
CHROME_REPO_URI="https://dl.google.com/linux/chrome/deb/"
CHROME_MANAGED_KEYRING="/etc/apt/keyrings/rldyour-google-chrome.asc"
CHROME_MANAGED_SOURCE="/etc/apt/sources.list.d/rldyour-google-chrome.sources"
CHROME_DEFAULTS_FILE="/etc/default/google-chrome"

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
REQUIRED_STEPS=(browseros rustdesk google_chrome firefox_removal)
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
    rldyour::log "info" "[DRY-RUN] desktop customization: GNOME dock bottom, Russian layout, BrowserOS and RustDesk install, Google Chrome install, Firefox removal"
    return 0
  fi

  # Each step is independent: one failing step does not abort the others.
  # Steps that need sudo call nddev::_sudo_refresh first.
  info "Authenticating sudo (will be refreshed as needed)"
  sudo -v || die "sudo authentication failed — cannot continue"

  nddev::_step gnome_dock nddev::_gnome_dock_bottom
  nddev::_step russian_layout nddev::_russian_keyboard_layout
  nddev::_step browseros nddev::_install_desktop_deb browseros
  nddev::_step rustdesk nddev::_install_desktop_deb rustdesk
  nddev::_step google_chrome nddev::_install_google_chrome
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

# ----------------------------- pinned .deb applications -----------------------------

# Install one row from DESKTOP_DEBS. Idempotent: an already-installed package is
# preserved untouched. The download is SHA-256 verified before dpkg ever sees
# it, and a failure returns rather than exiting so the remaining steps still run.
nddev::_install_desktop_deb() {
  local wanted=$1 row name package url_x64 sha_x64 url_arm64 sha_arm64
  local url sha arch tmp

  for row in "${DESKTOP_DEBS[@]}"; do
    IFS=';' read -r name package url_x64 sha_x64 url_arm64 sha_arm64 <<<"$row"
    [ "$name" = "$wanted" ] && break
    name=""
  done
  if [ -z "$name" ]; then
    warn "no DESKTOP_DEBS row named ${wanted}"
    return 1
  fi

  arch="$(dpkg --print-architecture 2>/dev/null)"
  case "$arch" in
    amd64) url=$url_x64; sha=$sha_x64 ;;
    arm64) url=$url_arm64; sha=$sha_arm64 ;;
    *) url=""; sha="" ;;
  esac
  if [ -z "$url" ] || [ -z "$sha" ]; then
    warn "${name}: upstream publishes no ${arch:-unknown} build"
    nddev::_record "$name" skipped
    return 0
  fi

  info "Installing ${name} (pinned .deb, SHA-256 verified)"
  if dpkg-query -W -f='${Status}' "$package" 2>/dev/null |
    command grep -q "install ok installed"; then
    ok "${name} already installed"
    return 0
  fi

  nddev::_sudo_refresh
  tmp="$(mktemp --suffix=.deb)" || return 1
  if ! rldyour::download_verified_file "$url" "$sha" "$tmp"; then
    rm -f "$tmp"
    warn "${name} .deb download or SHA-256 verification failed"
    return 1
  fi
  ok "downloaded and verified ($(du -h "$tmp" | cut -f1))"

  sudo dpkg -i "$tmp" 2>/dev/null || sudo apt-get install -f -y 2>/dev/null
  rm -f "$tmp"

  # `die` here used to exit the whole script from inside a `step || warn`
  # chain, so a failed install silently skipped every step after it. A step
  # reports its own failure and returns.
  if dpkg-query -W -f='${Status}' "$package" 2>/dev/null |
    command grep -q "install ok installed"; then
    ok "${name} installed"
    return 0
  fi
  warn "${name} installation failed"
  return 1
}

# ----------------------------- Google Chrome -----------------------------

# Return 0 when $1 is a keyring whose single primary key matches the expected
# Chrome signing fingerprint. Mirrors the Docker key gate in server.sh: exactly
# one primary key, exact fingerprint, no trust-on-first-use.
nddev::_chrome_keyring_verifies() {
  local keyring=$1 primary
  [ -f "$keyring" ] || return 1
  primary="$(gpg --batch --show-keys --with-colons "$keyring" 2>/dev/null |
    awk -F: '
      $1 == "pub" { primary_count++; awaiting=1; next }
      $1 == "fpr" && awaiting { fpr = toupper($10); awaiting = 0 }
      END {
        if (primary_count != 1 || fpr == "") exit 1
        print fpr
      }
    ')" || return 1
  [ "$primary" = "$CHROME_KEY_FINGERPRINT" ]
}

# Find an apt source already pointing at the Chrome repository, whatever wrote
# it. Prints its path, or nothing.
nddev::_chrome_existing_source() {
  local file
  for file in /etc/apt/sources.list /etc/apt/sources.list.d/*.list \
    /etc/apt/sources.list.d/*.sources; do
    [ -f "$file" ] || continue
    # Google's cron writes `linux/chrome/deb`; a source created through
    # Ubuntu's repolib tooling uses `linux/chrome-stable/deb`. Either is the
    # same product and must not be duplicated.
    if command grep -qF 'dl.google.com/linux/chrome' "$file"; then
      printf '%s\n' "$file"
      return 0
    fi
  done
  return 1
}

# Extract the Signed-By keyring a source file names.
nddev::_chrome_source_keyring() {
  local file=$1
  command sed -n -E 's/^[[:space:]]*Signed-By:[[:space:]]*//p; s/.*\[[^]]*signed-by=([^] ]+).*/\1/p' \
    "$file" | head -1
}

nddev::_install_google_chrome() {
  info "Installing Google Chrome (signed apt source, stable channel)"
  local existing keyring tmp_key tmp_source

  if [ "$(dpkg --print-architecture 2>/dev/null)" != "amd64" ]; then
    warn "Google publishes no Linux build for this architecture"
    nddev::_record google_chrome skipped
    return 0
  fi

  # An existing source for the same repository -- typically written by Chrome's
  # own installer -- is preserved rather than duplicated. Two sources for one
  # repository make apt ambiguous, and the vendor's cron re-enables its own file
  # after a distro upgrade, so competing with it would never converge. What must
  # hold either way is the key.
  if existing="$(nddev::_chrome_existing_source)"; then
    keyring="$(nddev::_chrome_source_keyring "$existing")"
    if [ -z "$keyring" ]; then
      warn "existing Chrome apt source names no Signed-By keyring: $existing"
      return 1
    fi
    if ! nddev::_chrome_keyring_verifies "$keyring"; then
      warn "existing Chrome apt source is signed by an unverified key: $keyring"
      return 1
    fi
    ok "existing Chrome apt source verified against $CHROME_KEY_FINGERPRINT"
  else
    nddev::_sudo_refresh
    tmp_key="$(mktemp)"
    if ! curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
      "$CHROME_KEY_URL" --output "$tmp_key"; then
      rm -f "$tmp_key"
      warn "could not download the Chrome signing key"
      return 1
    fi
    if ! nddev::_chrome_keyring_verifies "$tmp_key"; then
      rm -f "$tmp_key"
      warn "Chrome signing key fingerprint verification failed"
      return 1
    fi
    tmp_source="$(mktemp)"
    cat >"$tmp_source" <<EOF
# Managed by macos-ubuntu-bootstrap: desktop-app-google-chrome-v1
Types: deb
URIs: ${CHROME_REPO_URI}
Suites: stable
Components: main
Architectures: amd64
Signed-By: ${CHROME_MANAGED_KEYRING}
EOF
    # Stop the package's postinst from adding a second, competing source. This
    # is the vendor's own documented switch, the same shape as Telegram's
    # externalupdater.d: work with the supported mechanism, never around it.
    sudo install -d -m 0755 /etc/apt/keyrings /etc/default
    printf 'repo_add_once="false"\nrepo_reenable_on_distupgrade="true"\n' |
      sudo tee "$CHROME_DEFAULTS_FILE" >/dev/null
    sudo install -m 0644 "$tmp_key" "$CHROME_MANAGED_KEYRING"
    sudo install -m 0644 "$tmp_source" "$CHROME_MANAGED_SOURCE"
    rm -f "$tmp_key" "$tmp_source"
    ok "installed managed Chrome apt source verified against $CHROME_KEY_FINGERPRINT"
    sudo apt-get update -qq || true
  fi

  if dpkg-query -W -f='${Status}' google-chrome-stable 2>/dev/null |
    command grep -q "install ok installed"; then
    ok "Google Chrome already installed"
    return 0
  fi

  nddev::_sudo_refresh
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y \
    --no-install-recommends google-chrome-stable || {
    warn "Google Chrome installation failed"
    return 1
  }
  ok "Google Chrome installed"
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
