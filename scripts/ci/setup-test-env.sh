#!/usr/bin/env bash
# Establish everything the test suite needs, and nothing it does not.
#
# The suite has two prerequisites the repository cannot assume: a hash-locked
# Python 3.14 environment, and a real zsh. `tests/test_terminal_portability.py`
# runs the managed rc files through the shell that actually reads them, so a
# missing zsh is not a skippable extra -- it is the difference between proving
# the template parses and asserting it.
#
# Both were established in `.github/workflows/pytest.yml` and nowhere else, so
# the module's own declared verification lane -- `.gds/repository.yaml`, which
# the control plane runs -- began with `uv venv` on a host that might have
# neither. On a host without uv it failed before a virtualenv existed; on a host
# with uv but without zsh it installed cleanly and then failed inside pytest, at
# a fixture, reported as a module defect. GitHub CI passed either way, because
# the reusable Python lane installed what the anchor omitted.
#
# This is the one place that establishes it. `pytest.yml` calls this, and
# `.gds/repository.yaml` declares it as `verification.commands.bootstrap` --
# a lane GDS runs first and never counts as proof, so a failure here says the
# check could not be attempted rather than that the module failed it.
#
# Idempotent: run it twice and the second run changes nothing.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

CONTRACT="config/rldyour-contract.json"
PYTHON_VERSION="3.14"

log() { printf 'setup-test-env: %s\n' "$1"; }

fail_prerequisite() {
  printf 'setup-test-env: prerequisite not met: %s\n' "$1" >&2
  exit 1
}

# --- apt-provided prerequisites -------------------------------------------
#
# Provisioned when this host allows it and refused loudly when it does not.
# For zsh in particular, the alternative -- skipping the terminal-portability
# tests when it is absent -- would turn a mandatory check into a best-effort
# one, and the lane would go green while proving less than it claims. A
# prerequisite that cannot be met has to say so.
apt_updated=0

# Root or sudo, whichever this host is. A container runs as root and has no
# sudo at all; a GitHub runner is a non-root user with passwordless sudo.
# Requiring sudo unconditionally would refuse to provision on exactly the
# disposable hosts this lane is meant for.
as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    env DEBIAN_FRONTEND=noninteractive "$@"
  else
    # `sudo -n` rather than `sudo`: a lane that blocks on a password prompt
    # hangs a runner until its timeout rather than reporting anything.
    sudo -n env DEBIAN_FRONTEND=noninteractive "$@"
  fi
}

can_install() {
  [ "$(uname -s)" = Linux ] || return 1
  command -v apt-get >/dev/null 2>&1 || return 1
  [ "$(id -u)" -eq 0 ] && return 0
  command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null
}

# `ensure_apt_package <command> <reason> <package>...`
#
# More than one package because `--no-install-recommends` is deliberate and has
# consequences: installing `curl` alone on a minimal image gives a curl that
# cannot complete a TLS handshake, because `ca-certificates` is a recommend
# rather than a dependency. The failure surfaces later, as
# `error setting certificate file`, on the download of a pinned artifact --
# which reads like a supply-chain problem and is not one.
ensure_apt_package() {
  local command_name=$1 reason=$2
  shift 2
  if command -v "$command_name" >/dev/null 2>&1; then
    return 0
  fi
  can_install || fail_prerequisite \
    "$command_name is missing and this host cannot install it (needs Linux, \
apt-get, and either root or passwordless sudo). Install $* and re-run: $reason"

  if [ "$apt_updated" -eq 0 ]; then
    log "apt-get update"
    as_root apt-get update -qq
    apt_updated=1
  fi
  log "installing $*"
  as_root apt-get install -y --no-install-recommends "$@" >/dev/null
  command -v "$command_name" >/dev/null 2>&1 ||
    fail_prerequisite "apt-get reported success but $command_name is still not on PATH"
}

# --- uv -------------------------------------------------------------------
#
# Acquired the way this repository acquires every pinned artifact: the exact
# version and SHA-256 the contract already states for a device, from a fixed
# versioned URL, verified before it is executed. An ambient uv is accepted only
# when it reports that same version -- a different one resolves the same
# lockfile with different code.
contract_value() {
  # python3 rather than jq: the suite runs on python3 by definition, so reading
  # the contract with it removes a prerequisite instead of adding one.
  python3 -c 'import json,sys
node = json.load(open(sys.argv[1]))
for key in sys.argv[2].split("."):
    node = node[key]
print(node)' "$CONTRACT" "$1"
}

uv_reports() { [ "$("$1" --version 2>/dev/null | awk '{ print $2 }')" = "$2" ]; }

ensure_uv() {
  local version sha256 triple archive stage
  version="$(contract_value runtime_support.ubuntu_uv)"
  stage="$REPO_ROOT/.uv"

  if command -v uv >/dev/null 2>&1 && uv_reports uv "$version"; then
    log "uv $version present"
    return 0
  fi

  # A previous run of this script staged uv here. `export PATH` does not survive
  # the process, so without this the second run downloads and verifies the same
  # artifact again -- work that is invisible locally and is a minute of every
  # CI run.
  if [ -x "$stage/uv" ] && uv_reports "$stage/uv" "$version"; then
    export PATH="$stage:$PATH"
    log "uv $version already staged"
    return 0
  fi

  case "$(uname -s)/$(uname -m)" in
    Linux/x86_64) triple=x86_64-unknown-linux-gnu; sha256="$(contract_value runtime_support.ubuntu_uv_sha256.x64)" ;;
    Linux/aarch64) triple=aarch64-unknown-linux-gnu; sha256="$(contract_value runtime_support.ubuntu_uv_sha256.arm64)" ;;
    *)
      fail_prerequisite \
        "uv $version is not on PATH and the contract tracks no artifact for \
$(uname -s)/$(uname -m). Install uv $version and re-run."
      ;;
  esac

  log "installing uv $version"
  archive="$(mktemp)"
  curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
    "https://github.com/astral-sh/uv/releases/download/${version}/uv-${triple}.tar.gz" \
    --output "$archive"
  echo "${sha256}  ${archive}" | sha256sum --check --status
  rm -rf "$stage"
  mkdir -p "$stage"
  tar -xzf "$archive" --strip-components=1 -C "$stage"
  rm -f "$archive"
  uv_reports "$stage/uv" "$version" ||
    fail_prerequisite "the staged uv artifact did not report $version"
  export PATH="$stage:$PATH"
  # GitHub Actions reads this; a local shell ignores it and uses the PATH above.
  if [ -n "${GITHUB_PATH:-}" ]; then
    echo "$stage" >>"$GITHUB_PATH"
  fi
  log "uv $version installed"
}

# --- the environment the tests run in -------------------------------------
#
# Dependencies come from the hash-locked lock through uv. pip is forbidden
# estate-wide, and an unpinned, unhashed install in the lane that proves the
# installer would be the wrong place to make an exception.
#
# The interpreter is pinned explicitly. `uv python install 3.14` makes 3.14
# available but does not make it `python`, so a bare `python -m pytest` once ran
# the suite on the runner's ambient interpreter while the lane was named
# `python (3.14)`. A virtualenv built from the requested version, invoked by
# path, makes the declared version the one that runs.
ensure_venv() {
  # `uv venv` refuses to write over an existing environment, so creating one
  # unconditionally made the second run fail -- in a script whose whole contract
  # is that running it twice is safe. Reuse the environment when it already
  # reports the pinned interpreter, and rebuild from scratch when it does not,
  # because a virtualenv built on a different interpreter is not the one the
  # lane is named after.
  if [ -x .venv/bin/python ] &&
    [ "$(.venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" = "$PYTHON_VERSION" ]; then
    log "reusing the existing $PYTHON_VERSION environment"
  else
    log "building the hash-locked $PYTHON_VERSION environment"
    uv venv --clear --python "$PYTHON_VERSION"
  fi
  # Idempotent on its own: already-satisfied pins are a no-op.
  uv pip install --require-hashes -r requirements-test.txt
  .venv/bin/python -c 'import sys; print("setup-test-env: python", ".".join(map(str, sys.version_info[:3])))'
  .venv/bin/python -m pytest --version >/dev/null
}

# Order matters: `contract_value` needs python3, and `ensure_uv` needs both
# python3 and curl. Everything below is idempotent, so a host that already has
# all of them does no work here at all.
#
# python3 is the interpreter that reads the contract, not the one the tests run
# on -- that one is the pinned 3.14 built by `ensure_venv` and invoked by path.
ensure_apt_package python3 \
  "it reads the pinned uv version and digest out of the contract" python3
ensure_apt_package curl \
  "it fetches the pinned uv artifact over TLS from its exact versioned URL" \
  curl ca-certificates
ensure_apt_package tar \
  "it unpacks the verified uv artifact" tar
ensure_apt_package zsh \
  "tests/test_terminal_portability.py runs the managed rc files through a real zsh" zsh

# The suite does not only read source. These four are the tools it drives, and
# each was found by running the declared lane on a host that did not have it --
# not by reading the tests, which name them through `subprocess` and give no
# hint until the call fails. A GitHub runner ships all of them, which is exactly
# why their absence from the anchor went unnoticed: the workflow could not fail
# for a reason the anchor's host would.
ensure_apt_package git \
  "the tracked-payload tests build real repositories to materialize" git
ensure_apt_package ssh-keygen \
  "the server-safety tests parse real authorized_keys material" openssh-client
ensure_apt_package gpg \
  "the desktop tests build real keyrings to prove the Chrome key gate" gnupg

ensure_uv
ensure_venv

log "ready"
