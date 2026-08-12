#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# shellcheck source=../lib/common.sh
# shellcheck disable=SC1091
source "$SCRIPT_DIR/../lib/common.sh"

RLDYOUR_DRY_RUN="${RLDYOUR_DRY_RUN:-1}"
STRICT="${RLDYOUR_STRICT:-0}"
SKIP_SYSTEM="${RLDYOUR_SKIP_SYSTEM:-0}"
SKIP_AI="${RLDYOUR_SKIP_AI:-0}"
SKIP_LSPS="${RLDYOUR_SKIP_LSPS:-0}"
SKIP_CHECKS="${RLDYOUR_SKIP_CHECKS:-0}"
GUI_ENABLED="${RLDYOUR_GUI_ENABLED:-1}"
LOCAL_EXECUTION_POLICY="${RLDYOUR_LOCAL_EXECUTION_POLICY:-source-lsp-only}"

HOMEBREW_PKG_VERSION="6.0.9"
HOMEBREW_PKG_SHA256="525599bd2dcbda29857120234336b0103ad5283a3dc8511f72066eeb917abd3c"
HOMEBREW_INSTALLER_TEAM="927JGANW46"

# Source/LSP-only workstation baseline. No Docker, project build orchestration,
# test runner, or local project runtime. Homebrew's LLVM distribution is present
# only because it is the supported clangd provider; this policy never invokes
# its compiler/linker for project builds.
# jdtls and kotlin-language-server are deliberately absent: their Homebrew
# formulae depend on openjdk and openjdk@21, so installing them pulled the JDK
# this manifest forbids by name. The estate has no Java sources, and its only
# Kotlin lives in a Flutter Android app whose toolchain is out of scope here.
BREW_SOURCE_PACKAGES=(
  git curl ca-certificates node bun uv python
  shellcheck shfmt llvm go gopls rust rust-analyzer dart-sdk docker-language-server
  vscode-langservers-extracted taplo marksman markdown-oxide
  terraform-ls helm-ls cmake-language-server
  pyright basedpyright ruff ty
  oxlint biome osv-scanner gitleaks semgrep hadolint actionlint
  yamllint markdownlint-cli2 prettier
  ripgrep fd eza bat git-delta jq yq ast-grep
  starship atuin fzf zoxide carapace antidote zsh-completions
  gh lazygit yazi xh jaq jnv duckdb difftastic tmux herdr
)

# Registry-backed language servers, pinned to exact versions for reproducibility
# (RVR-P2-003). This is a subset of the Ubuntu BUN_LSP_PACKAGES (6 of 13); the
# remaining LSPs (vscode-langservers-extracted, @taplo/cli, @biomejs/biome,
# oxlint, markdownlint-cli2, prettier, @ansible/ansible-language-server) arrive
# via Homebrew formulae in BREW_SOURCE_PACKAGES below, where exact pins are not
# possible. The 6 shared entries below are kept version-aligned with Ubuntu.
BUN_LSP_PACKAGES=(
  "typescript@7.0.2"
  "@vtsls/language-server@0.3.0"
  "yaml-language-server@1.24.0"
  "bash-language-server@5.6.0"
  "dockerfile-language-server-nodejs@0.15.0"
  "gh-actions-language-server@0.0.3"
)

GUI_CASKS=(ghostty cmux google-chrome chatgpt claude rustdesk telegram)

usage() {
  cat <<'EOF'
Usage: scripts/macos/install.sh

Internal macOS Apple Silicon installer. Use scripts/bootstrap.sh so profile,
GUI, safety, and verification settings are composed consistently.
EOF
}

ensure_homebrew() {
  if command -v brew >/dev/null 2>&1; then
    rldyour::log "ok" "Homebrew already installed"
    return 0
  fi
  if [ "$RLDYOUR_DRY_RUN" -eq 1 ]; then
    rldyour::log "info" "[DRY-RUN] download notarized Homebrew ${HOMEBREW_PKG_VERSION} package, verify tracked SHA-256 and Apple installer signature, then install"
    return 0
  fi
  local installer signature
  installer="$(mktemp -d)/Homebrew.pkg"
  trap 'rm -rf "$(dirname "$installer")"' RETURN
  rldyour::download_verified_file \
    "https://github.com/Homebrew/brew/releases/download/${HOMEBREW_PKG_VERSION}/Homebrew.pkg" \
    "$HOMEBREW_PKG_SHA256" "$installer"
  signature="$(/usr/sbin/pkgutil --check-signature "$installer" 2>&1)" || {
    rldyour::log "error" "Homebrew installer signature validation failed"
    return 1
  }
  printf '%s\n' "$signature" | grep -Fq "$HOMEBREW_INSTALLER_TEAM" || {
    rldyour::log "error" "Homebrew installer signer team mismatch"
    return 1
  }
  /usr/sbin/spctl --assess --type install --verbose=2 "$installer" >/dev/null 2>&1 || {
    rldyour::log "error" "Homebrew package failed Gatekeeper/notarization assessment"
    return 1
  }
  sudo /usr/sbin/installer -pkg "$installer" -target /
  rm -rf "$(dirname "$installer")"
  trap - RETURN
}

ensure_formula() {
  local formula="$1"
  if [ "$RLDYOUR_DRY_RUN" -eq 1 ] && ! command -v brew >/dev/null 2>&1; then
    rldyour::log "info" "[DRY-RUN] brew install ${formula}"
    return 0
  fi
  if brew list --formula "$formula" >/dev/null 2>&1; then
    rldyour::log "ok" "preserving installed Homebrew formula: $formula"
  else
    rldyour::run brew install "$formula"
  fi
}

install_source_packages() {
  rldyour::section "Install source/LSP-only Homebrew baseline"
  local formula
  for formula in "${BREW_SOURCE_PACKAGES[@]}"; do
    ensure_formula "$formula"
  done
  # `dart-sdk` backs the Dart analysis server and the `dart mcp-server` transport
  # (ADR 0006). Homebrew cannot pin an exact patch, so unlike Ubuntu there is no
  # receipt here — but the telemetry opt-out is identical on both platforms and
  # shares one helper.
  if [ "$RLDYOUR_DRY_RUN" -eq 1 ]; then
    rldyour::log "info" "[DRY-RUN] disable Dart telemetry reporting through 'dart --disable-analytics'"
  else
    rldyour::ensure_dart_telemetry_disabled "$(command -v dart)" || return 1
  fi
}

cask_app_path() {
  case "$1" in
    ghostty) printf '%s\n' "/Applications/Ghostty.app" ;;
    cmux) printf '%s\n' "/Applications/cmux.app" ;;
    chatgpt) printf '%s\n' "/Applications/ChatGPT.app" ;;
    claude) printf '%s\n' "/Applications/Claude.app" ;;
    google-chrome) printf '%s\n' "/Applications/Google Chrome.app" ;;
    rustdesk) printf '%s\n' "/Applications/RustDesk.app" ;;
    telegram) printf '%s\n' "/Applications/Telegram.app" ;;
    *) return 1 ;;
  esac
}

verify_existing_cask_app() {
  local cask="$1"
  local app_path="$2"
  [ -d "$app_path" ] || {
    rldyour::log "error" "existing cask destination is not an app bundle: $app_path"
    return 1
  }
  /usr/bin/codesign --verify --deep --strict "$app_path" >/dev/null 2>&1 || {
    rldyour::log "error" "existing unmanaged app failed code-signature verification: $app_path"
    return 1
  }
  /usr/sbin/spctl --assess --type execute "$app_path" >/dev/null 2>&1 || {
    rldyour::log "error" "existing unmanaged app failed Gatekeeper assessment: $app_path"
    return 1
  }
  rldyour::log "ok" "preserving signed and notarized unmanaged cask destination for $cask: $app_path"
}

ensure_cask() {
  local cask="$1"
  local app_path=""
  if [ "$RLDYOUR_DRY_RUN" -eq 1 ] && ! command -v brew >/dev/null 2>&1; then
    rldyour::log "info" "[DRY-RUN] brew install --cask ${cask}"
    return 0
  fi
  if brew list --cask "$cask" >/dev/null 2>&1; then
    rldyour::log "ok" "preserving installed Homebrew cask: $cask"
    return 0
  fi
  app_path="$(cask_app_path "$cask" || true)"
  if [ -n "$app_path" ] && [ -e "$app_path" ]; then
    verify_existing_cask_app "$cask" "$app_path"
    return 0
  fi
  rldyour::run brew install --cask "$cask"
}

# Set when a cask could not be installed. Reported at the end of main.
GUI_LAYER_FAILED=0

install_gui_apps() {
  if [ "$GUI_ENABLED" -ne 1 ]; then
    rldyour::log "info" "GUI apps disabled by --no-gui"
    return 0
  fi
  rldyour::section "Install verified macOS GUI applications"
  local cask failed=0
  # Attempt every cask, then report. This loop used to call ensure_cask bare
  # under `set -e`, so one unavailable cask -- a Homebrew rename, a notarization
  # change, a network blip -- aborted the whole script and stranded every layer
  # behind it: language servers, AI CLIs, and verification. That is the same failure this repository already
  # fixed twice on Ubuntu; the optional layer must never be able to take the
  # required ones down with it.
  for cask in "${GUI_CASKS[@]}"; do
    if ! ensure_cask "$cask"; then
      rldyour::log "error" "cask failed: ${cask}"
      failed=$((failed + 1))
    fi
  done
  if [ "$failed" -gt 0 ]; then
    GUI_LAYER_FAILED=$failed
    rldyour::log "error" "${failed} GUI cask(s) failed; later layers were still attempted"
  fi
  rldyour::log "info" "Installed the workstation GUI application set."
}

install_ai_runtimes() { rldyour::install_vendor_ai_clis; }

install_bun_lsps() {
  rldyour::section "Install registry-backed language servers"
  local entry name version
  for entry in "${BUN_LSP_PACKAGES[@]}"; do
    name="${entry%@*}"
    version="${entry##*@}"
    # Reproducible: skip only when the EXACT pinned version is already installed;
    # otherwise install the pin so a stale/divergent version is corrected.
    if bun pm ls -g 2>/dev/null | grep -Fq "${name}@${version}"; then
      rldyour::log "ok" "pinned Bun source tool present: ${entry}"
    else
      rldyour::run bun add -g --ignore-scripts "$entry"
    fi
  done
}

configure_cmux_hooks() {
  [ "$GUI_ENABLED" -eq 1 ] || return 0
  if command -v cmux >/dev/null 2>&1; then
    # Keep bootstrap non-interactive and scoped to owner-standard agents. The
    # generic setup command prompts for every detected integration and can
    # create unrelated configuration on an otherwise clean host.
    local agent
    # The active harness set that cmux integrates is codex only, per the
    # one-owner-per-harness policy (RVR-P1-004).
    # shellcheck disable=SC2043
    for agent in codex; do
      rldyour::run cmux hooks "$agent" install --yes
    done
  else
    rldyour::log "info" "cmux hooks will be configured after cmux first appears on PATH"
  fi
}

verify_apply() {
  if [ "$RLDYOUR_DRY_RUN" -eq 1 ]; then
    rldyour::log "info" "plan complete; verification runs only after apply"
  elif [ "$SKIP_CHECKS" -eq 0 ]; then
    RLDYOUR_GUI_ENABLED="$GUI_ENABLED" \
      bash "$SCRIPT_DIR/verify.sh" --strict
  fi
}

main() {
  if [ "${1:-}" = "--help" ]; then
    usage
    exit 0
  fi

  rldyour::assert_root "$REPO_ROOT"
  rldyour::ensure_path
  [ "$LOCAL_EXECUTION_POLICY" = "source-lsp-only" ] || {
    rldyour::log "error" "macOS must use source-lsp-only policy"
    exit 2
  }
  if [ "$RLDYOUR_DRY_RUN" -eq 0 ]; then
    if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
      rldyour::log "error" "supported macOS apply target is Apple Silicon (arm64)"
      exit 2
    fi
  fi

  rldyour::section "macos-ubuntu-bootstrap (macOS) installer"
  rldyour::log "info" "mode: $([ "$RLDYOUR_DRY_RUN" -eq 1 ] && echo dry-run || echo apply); gui: $GUI_ENABLED; policy: $LOCAL_EXECUTION_POLICY"

  if [ "$SKIP_SYSTEM" -eq 0 ]; then
    ensure_homebrew
    rldyour::ensure_path
    if command -v brew >/dev/null 2>&1 || [ "$RLDYOUR_DRY_RUN" -eq 1 ]; then
      install_source_packages
      install_gui_apps
    elif [ "$STRICT" -eq 1 ]; then
      rldyour::log "error" "Homebrew unavailable after installation"
      exit 1
    fi
    rldyour::ensure_git_perf
    rldyour::ensure_git_delta_config
    rldyour::install_terminal_configs "$REPO_ROOT/templates/terminal"
  else
    rldyour::log "warn" "system layer skipped by explicit recovery flag"
  fi

  [ "$SKIP_LSPS" -eq 1 ] || install_bun_lsps

  configure_cmux_hooks

  # Install vendor CLIs after the platform toolchain is available.
  [ "$SKIP_AI" -eq 1 ] || install_ai_runtimes
  if [ "$GUI_LAYER_FAILED" -ne 0 ]; then
    rldyour::log "error" "${GUI_LAYER_FAILED} GUI cask(s) failed; every other layer was still attempted"
    return 1
  fi
  verify_apply
  rldyour::log "info" "Run 'bash scripts/auth-handoff.sh' for user-controlled sign-in steps."
}

# Guard so the main flow only runs when executed directly, not when sourced.
# Mirrors scripts/ubuntu/install.sh and scripts/ubuntu/server.sh so macOS
# install.sh is safe to source from tests.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
