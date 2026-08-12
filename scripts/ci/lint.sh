#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

check_cmd() {
  if command -v "$1" >/dev/null 2>&1; then
    return 0
  fi
  echo "missing required command: $1" >&2
  exit 1
}

check_script() {
  local script=$1
  if [ ! -f "$script" ]; then
    echo "missing script: $script" >&2
    exit 1
  fi
}

check_cmd bash
check_cmd shellcheck

# Every owned shell file is checked. A hand-maintained allowlist silently
# skipped scripts/ubuntu/desktop.sh from the day it was added, and would have
# skipped scripts/remote-exec.sh too: the
# list is edited by whoever remembers, and a new file is exactly the case
# nobody remembers. Discovery inverts that default.
#
# EXCLUDED_PATHS holds paths that are deliberately not checked. It is empty on
# purpose -- add an entry only with the reason, never to silence a finding.
EXCLUDED_PATHS=()

# `mapfile` is bash 4.0+ and macOS still ships bash 3.2, where this script runs
# too. A read loop is the portable equivalent.
SCRIPT_PATHS=()
while IFS= read -r discovered; do
  SCRIPT_PATHS+=("$discovered")
done < <(find "$REPO_ROOT/scripts" -type f -name '*.sh' -print | sort)
if [ "${#SCRIPT_PATHS[@]}" -eq 0 ]; then
  echo "no shell scripts discovered under $REPO_ROOT/scripts" >&2
  exit 1
fi

filtered=()
for script in "${SCRIPT_PATHS[@]}"; do
  skip=0
  for excluded in ${EXCLUDED_PATHS[@]+"${EXCLUDED_PATHS[@]}"}; do
    [ "$script" = "$REPO_ROOT/$excluded" ] && skip=1 && break
  done
  [ "$skip" -eq 1 ] || filtered+=("$script")
done
SCRIPT_PATHS=("${filtered[@]}")
printf 'linting %d shell scripts\n' "${#SCRIPT_PATHS[@]}"

for script in "${SCRIPT_PATHS[@]}"; do
  check_script "$script"
  bash -n "$script"
done

for script in "${SCRIPT_PATHS[@]}"; do
  shellcheck -x "$script"
done

echo "scripts-lint-ok"
