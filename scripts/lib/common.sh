#!/usr/bin/env bash

set -euo pipefail

RLDYOUR_DRY_RUN="${RLDYOUR_DRY_RUN:-1}"

rldyour::log() {
  local level=$1
  shift
  printf '[%s] %s\n' "$level" "$*"
}

rldyour::run() {
  local -a cmd=("$@")
  local rendered=

  rendered=$(printf " %q" "${cmd[@]}")
  if [ "$RLDYOUR_DRY_RUN" -eq 1 ]; then
    printf '[DRY-RUN] %s\n' "${rendered# }"
    return 0
  fi
  "${cmd[@]}"
}

rldyour::sha256_file() {
  local path=$1
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{ print $1 }'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{ print $1 }'
  else
    rldyour::log "error" "sha256sum or shasum is required for artifact verification"
    return 1
  fi
}

# True when the current x86-64 CPU advertises AVX2. The standard Bun x64 build
# requires AVX2; older CPUs must use the bun-linux-x64-baseline artifact or they
# fail with SIGILL. Non-x86 architectures are not gated by this check.
rldyour::cpu_has_avx2() {
  grep -Eq '(^|[[:space:]])avx2([[:space:]]|$)' /proc/cpuinfo 2>/dev/null
}

rldyour::download_verified_file() {
  local url=$1
  local expected_sha256=$2
  local destination=$3
  local actual_sha256

  curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
    "$url" --output "$destination" || return 1
  actual_sha256="$(rldyour::sha256_file "$destination")" || return 1
  if [ "$actual_sha256" != "$expected_sha256" ]; then
    rldyour::log "error" "SHA-256 mismatch for ${url}: expected ${expected_sha256}, got ${actual_sha256}"
    return 1
  fi
}

rldyour::sha512_file() {
  local path=$1
  if command -v sha512sum >/dev/null 2>&1; then
    sha512sum "$path" | awk '{ print $1 }'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 512 "$path" | awk '{ print $1 }'
  else
    rldyour::log "error" "sha512sum or shasum is required for artifact verification"
    return 1
  fi
}

rldyour::download_verified_sha512_file() {
  local url=$1
  local expected_sha512=$2
  local destination=$3
  local actual_sha512

  curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
    "$url" --output "$destination" || return 1
  actual_sha512="$(rldyour::sha512_file "$destination")" || return 1
  if [ "$actual_sha512" != "$expected_sha512" ]; then
    rldyour::log "error" "SHA-512 mismatch for pinned artifact: ${url}"
    return 1
  fi
}

rldyour::require_cmd() {
  local name=$1
  local level=$2
  if command -v "$name" >/dev/null 2>&1; then
    rldyour::log "ok" "$name on PATH"
    return 0
  fi

  if [ "$level" = "required" ]; then
    rldyour::log "missing" "required command not found: $name"
    return 1
  fi

  rldyour::log "warn" "optional command not found: $name"
  return 0
}

rldyour::require_one_of_cmd() {
  local level=$1
  shift
  local names=("$@")
  local found_name=""

  for name in "${names[@]}"; do
    if command -v "$name" >/dev/null 2>&1; then
      rldyour::log "ok" "$name on PATH"
      found_name="$name"
      break
    fi
  done

  if [ -n "$found_name" ]; then
    return 0
  fi

  local alt="one of (${names[*]})"
  if [ "$level" = "required" ]; then
    rldyour::log "missing" "required command not found: $alt"
    return 1
  fi

  rldyour::log "warn" "optional command not found: $alt"
  return 0
}

rldyour::need_cmd() {
  local command_name=$1
  if command -v "$command_name" >/dev/null 2>&1; then
    printf '%s\n' "$command_name"
    return 0
  fi
  return 1
}

rldyour::section() {
  printf '\n==> %s\n' "$*"
}

rldyour::require_file() {
  local path=$1
  if [ ! -f "$path" ]; then
    rldyour::log "missing" "required file: $path"
    return 1
  fi
  rldyour::log "ok" "found file: $path"
}

rldyour::require_cmd_min_version() {
  local command_name=$1
  local min_version=$2
  local version_cmd=${3:-"--version"}

  if ! command -v "$command_name" >/dev/null 2>&1; then
    rldyour::log "missing" "$command_name not found"
    return 1
  fi

  local actual_version
  actual_version=$("$command_name" "$version_cmd" 2>/dev/null | head -n 1 | sed 's/^v//; s/^[^0-9]*//')
  if [ -z "$actual_version" ]; then
    # Some tools report their version on stderr. The Ubuntu Dart path reads both
    # streams for exactly that reason; this one discarded stderr and then passed
    # the check anyway, so a Dart that only answers on stderr satisfied a
    # minimum-version gate without its version ever being compared.
    actual_version=$("$command_name" "$version_cmd" 2>&1 | head -n 1 | sed 's/^v//; s/^[^0-9]*//')
  fi
  if [ -z "$actual_version" ]; then
    # Fail closed. A verifier that cannot read a version has not verified it,
    # and every equivalent Ubuntu check is an exact comparison that exits
    # non-zero here. "Skipping the numeric check" made the macOS gate weaker
    # than the Ubuntu one for the same invariant.
    rldyour::log "missing" "could not detect version for $command_name (expected >= $min_version)"
    return 1
  fi

  local normalized_actual
  normalized_actual="$(printf '%s' "$actual_version" | sed 's/[[:space:]].*//')"

  if [ "$(printf '%s\n%s\n' "$min_version" "$normalized_actual" | sort -V | head -n 1)" != "$min_version" ]; then
    rldyour::log "warn" "$command_name version check: $normalized_actual (expected >= $min_version)"
    return 1
  fi

  rldyour::log "ok" "$command_name version OK: $normalized_actual"
  return 0
}

rldyour::assert_root() {
  local dir=$1
  if [ ! -f "$dir/config/rldyour-contract.json" ]; then
    rldyour::log "error" "not inside module root: missing config/rldyour-contract.json in $dir"
    return 1
  fi
  return 0
}

rldyour::has_root() {
  local script_dir=$1
  local root_dir
  root_dir="$(cd "$script_dir/../.." && pwd)"
  if [ ! -d "$root_dir" ]; then
    return 1
  fi
  printf '%s\n' "$root_dir"
}

rldyour::ensure_path() {
  local -a candidates=(
    "$HOME/.local/bin"
    "$HOME/.cargo/bin"
    "$HOME/.bun/bin"
    "$HOME/go/bin"
    "$HOME/.rldyour/bin"
    "$HOME/.mimocode/bin"
    # nddev-codex-app installs its standalone CLI under its own target and
    # publishes no link into the managed prefix, so the harness target's bin
    # directory is the only place `codex` can be resolved from.
    "${RLDYOUR_CODEX_HOME:-$HOME/.codex}/bin"
    # Apple Silicon Homebrew. ensure_homebrew installs brew into /opt/homebrew
    # but the Homebrew installer only edits the login shell profile, never the
    # current process, so without this the macOS apply run cannot resolve `brew`
    # (or the dart/bun/node it just installed) right after installing it. The
    # dir guard makes this a no-op on Linux and on a pre-brew macOS pass.
    "/opt/homebrew/bin"
    "/opt/homebrew/sbin"
  )
  local prefix=""
  for p in "${candidates[@]}"; do
    if [ -d "$p" ]; then
      if [ -n "$prefix" ]; then
        prefix="$prefix:$p"
      else
        prefix="$p"
      fi
    fi
  done
  [ -z "$prefix" ] || PATH="$prefix:$PATH"
  export PATH
}

# Install or update a repository-owned file atomically. Existing files are
# changed only when they carry the supplied ownership marker.
rldyour::install_managed_file() {
  local dest=$1
  local marker=$2
  local mode=${3:-0644}
  local legacy_marker=${4:-}
  local explicitly_owned=${5:-0}
  local parent tmp

  parent="$(dirname "$dest")"
  if [ "${RLDYOUR_DRY_RUN:-1}" -eq 1 ]; then
    cat >/dev/null
    rldyour::log "info" "[DRY-RUN] install managed file: ${dest}"
    return 0
  fi

  mkdir -p "$parent" || return 1
  tmp="$(mktemp "${dest}.tmp.XXXXXX")" || return 1
  if ! cat >"$tmp"; then
    rm -f "$tmp"
    return 1
  fi
  chmod "$mode" "$tmp" || {
    rm -f "$tmp"
    return 1
  }

  if [ -L "$dest" ] || { [ -e "$dest" ] && [ ! -f "$dest" ]; }; then
    rm -f "$tmp"
    rldyour::log "error" "unmanaged path is not a regular file; preserved: ${dest}"
    return 1
  fi
  if [ -f "$dest" ]; then
    if grep -Fxq "$marker" "$dest"; then
      :
    elif [ -n "$legacy_marker" ] && grep -Fxq "$legacy_marker" "$dest"; then
      rldyour::log "info" "updating legacy repository-managed file: ${dest}"
    elif [ "$explicitly_owned" -eq 1 ]; then
      :
    else
      rm -f "$tmp"
      rldyour::log "error" "unmanaged file differs; preserved: ${dest}"
      return 1
    fi
  fi
  if [ -f "$dest" ] && cmp -s "$tmp" "$dest"; then
    rm -f "$tmp"
    chmod "$mode" "$dest" || return 1
    rldyour::log "ok" "managed file already current: ${dest}"
    return 0
  fi

  mv -f "$tmp" "$dest" || {
    rm -f "$tmp"
    return 1
  }
  rldyour::log "ok" "installed managed file: ${dest}"
}

# Official vendor installers are mutable URLs. The bootstrap downloads them to
# a temporary file and verifies the reviewed script digest before execution.
RLDYOUR_CLAUDE_INSTALLER_URL="https://claude.ai/install.sh"
RLDYOUR_CLAUDE_INSTALLER_SHA256="cde4f1702d3b1695f92b73d26888364e17bca476e17f0fd676484c951d36c125"
RLDYOUR_GROK_INSTALLER_URL="https://x.ai/cli/install.sh"
RLDYOUR_GROK_INSTALLER_SHA256="43d0943123edade1383a476a4f778674877acee7c1f98a00f094c4a0f7349321"
RLDYOUR_CODEX_VERSION="0.147.0"
RLDYOUR_CODEX_TARBALL="https://registry.npmjs.org/@openai/codex/-/codex-0.147.0.tgz"
RLDYOUR_CODEX_SHA512="1102c45de7001b6a6dc48ed4a41328d9347f81ae79f7afdcfceb1817fd0ba140e1e4900d67b2281aa97304459bb84550efa25e3c86ed4d6fe2842929d5aed9df"

rldyour::install_vendor_ai_clis() {
  rldyour::section "Install official AI CLIs (Codex, Claude Code, Grok Build)"
  if [ "${RLDYOUR_DRY_RUN:-1}" -eq 1 ]; then
    rldyour::log "info" "[DRY-RUN] install verified @openai/codex ${RLDYOUR_CODEX_VERSION} package"
    rldyour::log "info" "[DRY-RUN] execute reviewed Anthropic native installer after SHA-256 verification"
    rldyour::log "info" "[DRY-RUN] execute reviewed xAI native installer after SHA-256 verification"
  else
    local stage codex_tgz claude_script grok_script npm_bin
    stage="$(mktemp -d)" || return 1
    codex_tgz="$stage/codex.tgz"
    claude_script="$stage/claude-install.sh"
    grok_script="$stage/grok-install.sh"
    rldyour::download_verified_sha512_file "$RLDYOUR_CODEX_TARBALL" "$RLDYOUR_CODEX_SHA512" "$codex_tgz" || return 1
    npm_bin="$(command -v npm 2>/dev/null || true)"
    if [ -z "$npm_bin" ] && [ -x "$HOME/.local/share/rldyour/node/v24.18.0/bin/npm" ]; then
      npm_bin="$HOME/.local/share/rldyour/node/v24.18.0/bin/npm"
    fi
    [ -n "$npm_bin" ] || {
      rldyour::log "error" "npm is unavailable for the verified Codex package installation"
      return 1
    }
    "$npm_bin" install --global --prefix "$HOME/.local/share/rldyour/npm" "$codex_tgz" || return 1
    mkdir -p "$HOME/.local/bin" || return 1
    ln -sfn "$HOME/.local/share/rldyour/npm/bin/codex" "$HOME/.local/bin/codex" || return 1
    rldyour::download_verified_file "$RLDYOUR_CLAUDE_INSTALLER_URL" "$RLDYOUR_CLAUDE_INSTALLER_SHA256" "$claude_script" || return 1
    bash "$claude_script" stable || return 1
    rldyour::download_verified_file "$RLDYOUR_GROK_INSTALLER_URL" "$RLDYOUR_GROK_INSTALLER_SHA256" "$grok_script" || return 1
    bash "$grok_script" || return 1
  fi
  rldyour::install_ai_launchers
}

rldyour::install_ai_launchers() {
  local bin="$HOME/.local/bin"
  mkdir -p "$bin"
  rldyour::install_managed_file "$bin/cx" "# Managed by macos-ubuntu-bootstrap: ai-launcher-cx-v1" 0755 <<'EOF'
#!/bin/sh
# Managed by macos-ubuntu-bootstrap: ai-launcher-cx-v1
exec codex --dangerously-bypass-approvals-and-sandbox "$@"
EOF
  rldyour::install_managed_file "$bin/cl" "# Managed by macos-ubuntu-bootstrap: ai-launcher-cl-v1" 0755 <<'EOF'
#!/bin/sh
# Managed by macos-ubuntu-bootstrap: ai-launcher-cl-v1
exec claude --dangerously-skip-permissions "$@"
EOF
  rldyour::install_managed_file "$bin/gk" "# Managed by macos-ubuntu-bootstrap: ai-launcher-gk-v1" 0755 <<'EOF'
#!/bin/sh
# Managed by macos-ubuntu-bootstrap: ai-launcher-gk-v1
exec grok --permission-mode bypassPermissions --always-approve "$@"
EOF
}

rldyour::_isolated_python() {
  local python_bin=$1
  shift
  env -u PYTHONPATH -u PYTHONHOME "$python_bin" -I "$@"
}

rldyour::ensure_dart_telemetry_disabled() {
  local binary=$1
  local config="$HOME/.dart-tool/dart-flutter-telemetry.config"
  if [ ! -x "$binary" ]; then
    rldyour::log "error" "Dart telemetry opt-out needs an executable dart: ${binary}"
    return 1
  fi
  # Dart's unified analytics becomes a no-op when CI is set and therefore does
  # not persist the owner opt-out. Clear only that process-local marker so the
  # official switch materializes state that remains valid outside CI.
  env -u CI "$binary" --disable-analytics >/dev/null 2>&1 || {
    rldyour::log "error" "'dart --disable-analytics' failed; Dart telemetry state is unknown"
    return 1
  }
  if [ ! -f "$config" ] || [ -L "$config" ]; then
    rldyour::log "error" "Dart telemetry config is missing or not a regular file: ${config}"
    return 1
  fi
  # A conflicting `reporting=1` must fail rather than be averaged away. Upstream
  # resolves duplicate keys conservatively, but this gate exists to prove the
  # opt-out, not to reason about upstream precedence rules.
  if ! grep -Fxq 'reporting=0' "$config" || grep -Fxq 'reporting=1' "$config"; then
    rldyour::log "error" "Dart telemetry is not provably disabled in ${config}"
    return 1
  fi
  rldyour::log "ok" "Dart telemetry reporting disabled (${config})"
}

rldyour::_managed_tree_permissions() {
  local mode=$1 root=$2
  case "$mode" in normalize|validate) ;; *) return 2 ;; esac
  rldyour::_isolated_python python3 -I - "$mode" "$root" <<'PY'
import os
import pathlib
import stat
import sys

mode, raw_root = sys.argv[1:]
root = pathlib.Path(raw_root)
root_real = root.resolve(strict=True)
uid = os.getuid()


def inspect(path: pathlib.Path) -> None:
    metadata = path.lstat()
    if metadata.st_uid != uid:
        raise SystemExit(f"runtime path has a foreign owner: {path}")
    if stat.S_ISLNK(metadata.st_mode):
        try:
            path.resolve(strict=True).relative_to(root_real)
        except (FileNotFoundError, ValueError):
            raise SystemExit(f"runtime symlink escaped its content-addressed root: {path}")
        return
    if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
        raise SystemExit(f"runtime contains an unsupported file type: {path}")
    permissions = stat.S_IMODE(metadata.st_mode)
    if mode == "normalize" and permissions & 0o022:
        path.chmod(permissions & ~0o022)
        metadata = path.lstat()
    if metadata.st_mode & 0o022:
        raise SystemExit(f"runtime path is group/world-writable: {path}")


inspect(root)
for directory, directories, files in os.walk(root, followlinks=False):
    base = pathlib.Path(directory)
    for name in directories + files:
        inspect(base / name)
PY
}

# --- Terminal layer# --- Terminal layer ----------------------------------------------------------

# Global git performance keys for agent-heavy repositories.
rldyour::ensure_git_perf() {
  rldyour::section "Configure git performance keys (global)"
  rldyour::run git config --global core.fsmonitor true
  rldyour::run git config --global core.untrackedCache true
  rldyour::run git config --global fetch.writeCommitGraph true
}

# git-delta as the human pager. Pagers never fire on pipes, so agents are
# unaffected; skipped entirely when delta is not on PATH (e.g. minimal server).
rldyour::ensure_git_delta_config() {
  rldyour::section "Configure git-delta pager (global)"
  if ! command -v delta >/dev/null 2>&1; then
    rldyour::log "warn" "delta not on PATH; skipping pager config"
    return 0
  fi
  rldyour::run git config --global core.pager delta
  rldyour::run git config --global interactive.diffFilter "delta --color-only"
  rldyour::run git config --global delta.navigate true
  rldyour::run git config --global delta.features "side-by-side line-numbers"
}

# Install one config template. Contract: create when absent; when present and
# identical -> ok; when present and different -> KEEP the user's file and
# point at the template. User edits are never clobbered.
rldyour::install_config_template() {
  local src="$1" dest="$2"
  if [ ! -f "$src" ]; then
    rldyour::log "warn" "template missing: $src"
    return 0
  fi
  if [ -f "$dest" ]; then
    if cmp -s "$src" "$dest"; then
      rldyour::log "ok" "$(basename "$dest") already current"
    else
      rldyour::log "warn" "$(basename "$dest") exists and differs -- kept as-is; template: $src"
    fi
    return 0
  fi
  if [ "${RLDYOUR_DRY_RUN:-1}" -eq 1 ]; then
    rldyour::log "info" "[DRY-RUN] install $src -> $dest"
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  cp "$src" "$dest"
  rldyour::log "ok" "installed $(basename "$dest")"
}

# Add or refresh one small, owned source block while preserving every byte
# outside that block. Existing shell files are backed up before the first
# mutation. Symlinks and non-regular paths are never followed or replaced.
rldyour::_ensure_managed_shell_source() {
  local dest=$1 dropin=$2 label=$3
  local begin="# >>> macos-ubuntu-bootstrap managed ${label} >>>"
  local end="# <<< macos-ubuntu-bootstrap managed ${label} <<<"
  local parent tmp backup_root

  if [ -L "$dest" ] || { [ -e "$dest" ] && [ ! -f "$dest" ]; }; then
    rldyour::log "error" "shell startup path is not a regular file; preserved: ${dest}"
    return 1
  fi
  if [ "${RLDYOUR_DRY_RUN:-1}" -eq 1 ]; then
    rldyour::log "info" "[DRY-RUN] ensure ${dest} sources ${dropin} through an owned block"
    return 0
  fi
  command -v python3 >/dev/null 2>&1 || {
    rldyour::log "error" "python3 is required to update shell source blocks safely"
    return 1
  }

  parent="$(dirname "$dest")"
  mkdir -p "$parent" || return 1
  tmp="$(mktemp "${dest}.tmp.XXXXXX")" || return 1
  if [ -f "$dest" ]; then
    cp -p "$dest" "$tmp" || { rm -f "$tmp"; return 1; }
  else
    chmod 0644 "$tmp" || { rm -f "$tmp"; return 1; }
  fi
  if ! rldyour::_isolated_python python3 - "$dest" "$tmp" "$dropin" "$begin" "$end" <<'PY'
from pathlib import Path
import sys

dest = Path(sys.argv[1])
output = Path(sys.argv[2])
dropin, begin, end = sys.argv[3:]
source = dest.read_text(encoding="utf-8") if dest.exists() else ""
if source.count(begin) != source.count(end):
    raise SystemExit("unbalanced managed shell source markers")
if source.count(begin) > 1:
    raise SystemExit("duplicate managed shell source markers")

block = f'{begin}\nsource "$HOME/{dropin}"\n{end}'
if begin in source:
    start = source.index(begin)
    stop = source.index(end, start) + len(end)
    rendered = source[:start] + block + source[stop:]
else:
    separator = "" if not source else ("" if source.endswith("\n") else "\n")
    rendered = source + separator + block + "\n"
output.write_text(rendered, encoding="utf-8")
PY
  then
    rm -f "$tmp"
    rldyour::log "error" "managed shell source block is malformed; preserved: ${dest}"
    return 1
  fi

  if [ -f "$dest" ] && cmp -s "$dest" "$tmp"; then
    rm -f "$tmp"
    rldyour::log "ok" "managed shell source already current: ${dest}"
    return 0
  fi
  if [ -f "$dest" ]; then
    backup_root="$HOME/.local/share/rldyour/backups/shell/$(date -u +%Y%m%dT%H%M%SZ)-$$"
    mkdir -p "$backup_root" || { rm -f "$tmp"; return 1; }
    chmod 0700 "$backup_root" || { rm -f "$tmp"; return 1; }
    cp -p "$dest" "$backup_root/$(basename "$dest")" || { rm -f "$tmp"; return 1; }
    rldyour::log "info" "backed up shell startup file: ${backup_root}/$(basename "$dest")"
  fi
  mv -f "$tmp" "$dest" || { rm -f "$tmp"; return 1; }
  rldyour::log "ok" "installed managed shell source block: ${dest}"
}

rldyour::verify_terminal_environment() {
  local shell_dump expected_bin="$HOME/.local/bin"
  local -a required_cmds=(codex claude grok cx cl gk)
  command -v zsh >/dev/null 2>&1 || {
    rldyour::log "error" "zsh is required for managed terminal verification"
    return 1
  }
  shell_dump="$(RLDYOUR_VERIFY_CMDS="${required_cmds[*]}" zsh -l -c '
    printf "__RLDYOUR_PATH__=%s\n" "$PATH"
    for name in ${=RLDYOUR_VERIFY_CMDS}; do
      resolved="$(command -v "$name")" || exit 1
      printf "__RLDYOUR_CMD_%s__=%s\n" "$name" "$resolved"
    done
  ' 2>/dev/null)" || {
    rldyour::log "error" "fresh zsh login environment verification failed"
    return 1
  }
  rldyour::_isolated_python python3 - "$shell_dump" "$expected_bin" <<'PY'
import sys

values = {}
for line in sys.argv[1].splitlines():
    if line.startswith("__RLDYOUR_") and "=" in line:
        key, value = line.split("=", 1)
        values[key] = value
expected_bin = sys.argv[2]
required = {"__RLDYOUR_PATH__"}
required.update(f"__RLDYOUR_CMD_{name}__" for name in ("codex", "claude", "grok", "cx", "cl", "gk"))
commands = [
    key[len("__RLDYOUR_CMD_"):-len("__")]
    for key in values
    if key.startswith("__RLDYOUR_CMD_")
]
if not required <= values.keys():
    raise SystemExit("fresh zsh environment returned an incomplete contract")
path = values["__RLDYOUR_PATH__"]
if path.split(":", 1)[0] != expected_bin:
    raise SystemExit("managed user bin is not first on fresh zsh PATH")
for name in commands:
    resolved = values[f"__RLDYOUR_CMD_{name}__"]
    if not resolved.startswith(expected_bin + "/"):
        raise SystemExit(f"managed command resolved outside {expected_bin}: {resolved}")
PY
  rldyour::log "ok" "fresh zsh login environment resolves all managed AI commands"
}

# Clone (or re-point) a git repository to an EXACT pinned commit at a managed
# path. Idempotent: an already-pinned clean checkout is a no-op and never
# re-clones; a non-git path at the destination is fail-closed and preserved.
rldyour::_ensure_pinned_git_checkout() {
  local url=$1 sha=$2 dir=$3 head origin
  if [ -e "$dir" ] || [ -L "$dir" ]; then
    if [ -L "$dir" ] || [ ! -d "$dir/.git" ]; then
      rldyour::log "error" "unmanaged non-git path at pinned clone dir; preserved: ${dir}"
      return 1
    fi
    # A managed checkout must point at the canonical remote: a repo sitting at
    # the right commit but a different origin is not trusted.
    origin="$(git -C "$dir" remote get-url origin 2>/dev/null || true)"
    if [ "$origin" != "$url" ]; then
      rldyour::log "error" "pinned clone dir has unexpected origin (${origin:-none} != ${url}); preserved: ${dir}"
      return 1
    fi
    head="$(git -C "$dir" rev-parse HEAD 2>/dev/null || true)"
    # Fast path ONLY when the commit matches AND the working tree is pristine.
    # These bytes are later compiled into the executable plugin bundle, so a
    # modified tracked file or an untracked drop-in must not be trusted just
    # because HEAD happens to match the pin.
    if [ "$head" = "$sha" ] && [ -z "$(git -C "$dir" status --porcelain 2>/dev/null)" ]; then
      # The content is provably the pinned commit, but its modes are not proven
      # by that: an earlier clone may have landed group-writable. Normalize on the
      # fast path too, or a device stays broken forever because the fast path is
      # the only one it ever takes again.
      rldyour::_harness_checkout_permissions "$dir" || return 1
      return 0
    fi
    git -C "$dir" fetch --quiet --tags origin || {
      rldyour::log "error" "failed to fetch pinned updates for ${dir}"
      return 1
    }
  else
    mkdir -p "${dir%/*}" || return 1
    git clone --quiet "$url" "$dir" || {
      rldyour::log "error" "failed to clone ${url}"
      return 1
    }
  fi
  # Restore EXACTLY the pinned commit and scrub any tracked or untracked drift so
  # the materialized bytes are precisely the reviewed commit — never a dirty or
  # locally substituted worktree.
  git -C "$dir" checkout --quiet --detach "$sha" || {
    rldyour::log "error" "pinned commit ${sha} not found in ${dir}"
    return 1
  }
  git -C "$dir" reset --quiet --hard "$sha" || {
    rldyour::log "error" "failed to reset ${dir} to ${sha}"
    return 1
  }
  git -C "$dir" clean -ffdx --quiet || {
    rldyour::log "error" "failed to scrub untracked drift in ${dir}"
    return 1
  }
  rldyour::_harness_checkout_permissions "$dir" || return 1
}

# `git clone` and `git checkout` create files under the caller's umask, and this
# tree is later compiled into an executable plugin bundle whose consumer refuses a
# group- or world-writable source. Under `umask 002` the clone lands with 252
# group-writable paths and nddev-codex-app's `install-builder` fails closed with
# "nddev-builder source plugin tree must not be writable by group or others" —
# after this function had already reported success. Because the harness layer runs
# ahead of every other layer under `set -euo pipefail`, that turned an
# environment-dependent mode into a total device-apply abort, the same pathology
#
# Normalize rather than fail: the bytes are provably the pinned commit, so
# tightening their modes cannot change what gets installed, and refusing would
# leave every `umask 002` host permanently unable to bootstrap.
rldyour::_harness_checkout_permissions() {
  local dir=$1
  rldyour::_managed_tree_permissions normalize "$dir" || {
    rldyour::log "error" "could not normalize permissions on the pinned checkout: ${dir}"
    return 1
  }
}

# Materialize an OFFLINE antidote plugin bundle shared by macOS and Ubuntu:
# ensure antidote is present, pre-clone every plugin at its pinned SHA into
# antidote's clone home, then compile the static ~/.zsh_plugins.zsh that shell
# startup sources with zero network. Idempotent: a second run re-verifies pinned
# SHAs and never re-clones a clean, already-pinned repo.
rldyour::materialize_zsh_plugins() {
  local manifest="$HOME/.zsh_plugins.txt"
  # getantidote/antidote pinned commit for the plain-Ubuntu clone path.
  local antidote_pin="4913257e0ae3fee2a77e7189e526fe55b6ff9536"
  local antidote_home="${XDG_CACHE_HOME:-$HOME/.cache}/antidote"
  local antidote_zsh="" candidate line repo sha dir bundle tmp
  local -a antidote_candidates=(
    /opt/homebrew/opt/antidote/share/antidote/antidote.zsh
    /usr/local/opt/antidote/share/antidote/antidote.zsh
    /home/linuxbrew/.linuxbrew/opt/antidote/share/antidote/antidote.zsh
    "$HOME/.antidote/antidote.zsh"
  )

  rldyour::section "Materialize offline antidote plugin bundle"

  if [ "${RLDYOUR_DRY_RUN:-1}" -eq 1 ]; then
    rldyour::log "info" "[DRY-RUN] ensure antidote (brew, else git clone getantidote/antidote@${antidote_pin} to \$HOME/.antidote), pre-clone every pinned plugin from ${manifest} into ${antidote_home}, then compile \$HOME/.zsh_plugins.zsh"
    return 0
  fi

  command -v git >/dev/null 2>&1 || {
    rldyour::log "error" "git is required to materialize the antidote plugin bundle"
    return 1
  }
  command -v zsh >/dev/null 2>&1 || {
    rldyour::log "error" "zsh is required to compile the antidote plugin bundle"
    return 1
  }
  [ -r "$manifest" ] || {
    rldyour::log "error" "plugin manifest is missing: ${manifest}"
    return 1
  }

  # 1. Ensure antidote.zsh is available: brew provides it on macOS/linuxbrew;
  #    otherwise clone getantidote/antidote at the pinned SHA to $HOME/.antidote,
  #    matching the path templates/terminal/zshrc already probes.
  for candidate in "${antidote_candidates[@]}"; do
    if [ -r "$candidate" ]; then
      antidote_zsh="$candidate"
      break
    fi
  done
  if [ -z "$antidote_zsh" ]; then
    rldyour::_ensure_pinned_git_checkout \
      "https://github.com/getantidote/antidote" "$antidote_pin" "$HOME/.antidote" || return 1
    antidote_zsh="$HOME/.antidote/antidote.zsh"
    [ -r "$antidote_zsh" ] || {
      rldyour::log "error" "antidote clone did not provide antidote.zsh: ${antidote_zsh}"
      return 1
    }
  fi

  # 2. Pre-clone every plugin at its pinned SHA into antidote's full-style clone
  #    home ($ANTIDOTE_HOME/github.com/<owner>/<repo>) so neither bundling nor
  #    shell startup ever reaches the network.
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|\#*) continue ;; esac
    repo="${line%%[[:space:]]*}"
    case "$repo" in */*) ;; *) continue ;; esac
    sha=""
    if [[ "$line" =~ pin[[:space:]]+([0-9a-f]{40}) ]]; then
      sha="${BASH_REMATCH[1]}"
    fi
    [ -n "$sha" ] || {
      rldyour::log "error" "plugin ${repo} has no pinned SHA in ${manifest}"
      return 1
    }
    dir="$antidote_home/github.com/$repo"
    rldyour::_ensure_pinned_git_checkout "https://github.com/$repo" "$sha" "$dir" || return 1
  done < "$manifest"

  # 3. Compile the static bundle. Every clone is present at its pinned SHA, so
  #    antidote sources them by path and never clones — the output is pure
  #    `source`/`fpath` lines that shell startup runs offline.
  bundle="$HOME/.zsh_plugins.zsh"
  tmp="$(mktemp "${bundle}.tmp.XXXXXX")" || return 1
  if ! ANTIDOTE_HOME="$antidote_home" \
      zsh -fc 'source "$1"; antidote bundle' antidote-bundle "$antidote_zsh" \
      < "$manifest" > "$tmp"; then
    rm -f "$tmp"
    rldyour::log "error" "antidote failed to compile the static plugin bundle"
    return 1
  fi
  [ -s "$tmp" ] || {
    rm -f "$tmp"
    rldyour::log "error" "compiled antidote bundle is empty"
    return 1
  }
  mv -f "$tmp" "$bundle" || { rm -f "$tmp"; return 1; }
  chmod 0644 "$bundle" 2>/dev/null || true
  rldyour::log "ok" "compiled offline antidote plugin bundle: ${bundle}"
}

rldyour::install_terminal_configs() {
  local tpl_dir="$1"
  rldyour::section "Install terminal shell configs (zsh-first, agent-gated)"
  rldyour::install_managed_file \
    "$HOME/.config/rldyour/zshenv" \
    "# Managed by macos-ubuntu-bootstrap: terminal-zshenv-v1" 0644 \
    <"$tpl_dir/zshenv"
  rldyour::install_managed_file \
    "$HOME/.config/rldyour/zprofile" \
    "# Managed by macos-ubuntu-bootstrap: terminal-zprofile-v1" 0644 \
    <"$tpl_dir/zprofile"
  rldyour::_ensure_managed_shell_source \
    "$HOME/.zshenv" ".config/rldyour/zshenv" "zshenv-v1"
  rldyour::_ensure_managed_shell_source \
    "$HOME/.zprofile" ".config/rldyour/zprofile" "zprofile-v1"
  rldyour::install_config_template "$tpl_dir/zshrc"           "$HOME/.zshrc"
  rldyour::install_config_template "$tpl_dir/zsh_plugins.txt" "$HOME/.zsh_plugins.txt"
  rldyour::install_config_template "$tpl_dir/starship.toml"   "$HOME/.config/starship.toml"
  rldyour::materialize_zsh_plugins
}
