#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
# shellcheck disable=SC1091
source "$SCRIPT_DIR/../lib/common.sh"

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
rldyour::require_cmd_min_version herdr 0.8 --version
# Dart backs the analysis server and the `dart-flutter` MCP transport. Homebrew
# cannot pin an exact patch, so the floor is a major/minor gate plus proof that
# the mcp-server subcommand exists (a Dart SDK below 3.9 resolves but cannot
# serve MCP at all, which would leave the declared marketplace server broken).
rldyour::require_cmd_min_version dart 3.12 --version
dart mcp-server --version >/dev/null 2>&1 || {
  rldyour::log "missing" "'dart mcp-server' transport for the dart-flutter MCP server"
  exit 1
}
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
