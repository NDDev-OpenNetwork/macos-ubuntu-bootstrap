#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
# shellcheck disable=SC1091
source "$SCRIPT_DIR/../lib/common.sh"

HERDR_VERSION="0.8.0"
HERDR_MACOS_AARCH64_SHA256="d53a9f93fccfdfcc55632927bf51002f5add0aa7990bcdf508ffbd84ac658178"
HERDR_MACOS_AARCH64_URL="https://github.com/herdrdev/herdr/releases/download/v0.8.0/herdr-macos-aarch64"

STRICT=0
GUI_ENABLED="${RLDYOUR_GUI_ENABLED:-1}"
for arg in "$@"; do
  case "$arg" in
    --strict) STRICT=1 ;;
    --no-gui) GUI_ENABLED=0 ;;
    --help)
      echo "Usage: scripts/macos/verify.sh [--strict] [--no-gui]"
      exit 0
      ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

rldyour::ensure_path
rldyour::section "Verify macOS source/LSP workstation"

required_cmds=(
  git curl node bun uv python3 shellcheck shfmt clangd
  go gopls rustc cargo rust-analyzer dart
  pyright pyright-langserver basedpyright ruff
  tsc vtsls yaml-language-server bash-language-server docker-langserver
  vscode-html-language-server vscode-css-language-server vscode-json-language-server
  taplo marksman terraform-ls cmake-language-server
  herdr
  codex claude grok cx cl gk
)
for cmd in "${required_cmds[@]}"; do
  rldyour::require_cmd "$cmd" required
done
rldyour::require_one_of_cmd required docker-language-server docker-langserver

rldyour::require_cmd_min_version node 20.19 --version
# Prompt/history/completion + uv/bun pillars are provisioned by Homebrew on
# macOS. brew tracks upstream and cannot pin an arbitrary patch, so — unlike the
# Ubuntu path, which installs these as content-addressed pinned standalone
# artifacts with an exact receipt — macOS cannot carry an exact receipt here.
# This asymmetry is intentional (brew has no exact-pin mechanism, and the wider
# LSP formula set has no standalone artifacts). We at least fail closed on gross
# drift/downgrade with conservative version floors instead of a silent
# presence-only check; a fresh brew install always satisfies them. Full
# content-addressed macOS parity (porting these pillars to the standalone
# artifact path) is a tracked follow-up.
rldyour::require_cmd_min_version uv 0.11 --version
rldyour::require_cmd_min_version bun 1.3 --version
rldyour::require_cmd_min_version starship 1.0 --version
rldyour::require_cmd_min_version atuin 18.0 --version
rldyour::require_cmd_min_version carapace 1.0 --version
herdr_root="$HOME/.local/share/rldyour/herdr/${HERDR_VERSION}"
herdr_target="$herdr_root/herdr"
herdr_receipt="$herdr_root/.receipt"
herdr_launcher="$HOME/.local/bin/herdr"
[ ! -L "$herdr_root" ] && [ -d "$herdr_root" ] && \
  [ "$(find "$herdr_root" -mindepth 1 -maxdepth 1 -print | LC_ALL=C sort)" = "$(printf '%s\n%s\n' "$herdr_receipt" "$herdr_target" | LC_ALL=C sort)" ] || {
  rldyour::log "missing" "Herdr exact managed root shape"
  exit 1
}
[ -f "$herdr_target" ] && [ ! -L "$herdr_target" ] && [ -x "$herdr_target" ] || {
  rldyour::log "missing" "managed Herdr target: ${herdr_target}"
  exit 1
}
[ "$(rldyour::sha256_file "$herdr_target")" = "$HERDR_MACOS_AARCH64_SHA256" ] || {
  rldyour::log "missing" "Herdr exact managed macOS artifact checksum"
  exit 1
}
[ -L "$herdr_launcher" ] && [ "$(readlink "$herdr_launcher")" = "$herdr_target" ] || {
  rldyour::log "missing" "Herdr exact managed launcher"
  exit 1
}
[ "$(command -v herdr)" = "$herdr_launcher" ] || {
  rldyour::log "missing" "managed Herdr launcher must win PATH resolution"
  exit 1
}
herdr_expected_receipt="# Managed by macos-ubuntu-bootstrap: macos-herdr-runtime-v1
version=${HERDR_VERSION}
sha256=${HERDR_MACOS_AARCH64_SHA256}
source=${HERDR_MACOS_AARCH64_URL}"
[ -f "$herdr_receipt" ] && [ ! -L "$herdr_receipt" ] && \
  [ "$(cat "$herdr_receipt")" = "$herdr_expected_receipt" ] || {
  rldyour::log "missing" "Herdr exact managed receipt"
  exit 1
}
[ "$(stat -f '%Lp' "$herdr_root")" = 755 ] && \
  [ "$(stat -f '%Lp' "$herdr_target")" = 755 ] && \
  [ "$(stat -f '%Lp' "$herdr_receipt")" = 600 ] || {
  rldyour::log "missing" "Herdr exact managed permissions"
  exit 1
}
rldyour::_managed_tree_permissions validate "$herdr_root" || exit 1
[ "$("$herdr_target" --version 2>/dev/null | sed -E 's/^[^0-9]*([0-9]+\.[0-9]+\.[0-9]+).*/\1/' | head -n 1)" = "$HERDR_VERSION" ] || {
  rldyour::log "missing" "Herdr exact managed version ${HERDR_VERSION}"
  exit 1
}
rldyour::log "ok" "Herdr exact managed macOS runtime ${HERDR_VERSION}"
# Dart backs the analysis server and the `dart-flutter` MCP transport. Homebrew
# cannot pin an exact patch, so the floor is a major/minor gate plus proof that
# the mcp-server subcommand exists (a Dart SDK below 3.9 resolves but cannot
# serve MCP at all, which would leave the declared marketplace server broken).
rldyour::require_cmd_min_version dart 3.12 --version
dart mcp-server --version >/dev/null 2>&1 || {
  rldyour::log "missing" "'dart mcp-server' transport for the dart-flutter MCP server"
  exit 1
}
rldyour::observe_dart_telemetry_config
rldyour::verify_terminal_environment

if [ "$GUI_ENABLED" -eq 1 ]; then
  for app in Ghostty cmux "Google Chrome" ChatGPT Claude RustDesk Telegram; do
    [ -d "/Applications/${app}.app" ] || {
      rldyour::log "missing" "required GUI app: /Applications/${app}.app"
      exit 1
    }
  done
fi

if command -v docker >/dev/null 2>&1; then
  rldyour::log "warn" "unmanaged Docker is present; this desktop bootstrap neither uses nor removes it"
else
  rldyour::log "ok" "desktop policy: Docker is absent"
fi

[ "$STRICT" -eq 0 ] || rldyour::log "ok" "strict macOS verification passed"
