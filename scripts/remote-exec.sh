#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/remote-exec.sh --host <ssh-host> --remote-repo <absolute-path> -- <command> [args...]

Run on a provisioned Ubuntu server only when both repositories are clean and
point at the same exact commit. No worktree or credentials are copied.
EOF
}

host="" remote_repo=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --host) host="${2:?--host requires an SSH destination}"; shift 2 ;;
    --remote-repo) remote_repo="${2:?--remote-repo requires an absolute path}"; shift 2 ;;
    --) shift; break ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[ -n "$host" ] || { echo "--host is required" >&2; exit 2; }
case "$host" in *[!A-Za-z0-9._@:-]*) echo "unsafe SSH destination" >&2; exit 2 ;; esac
case "$host" in -*) echo "unsafe SSH destination" >&2; exit 2 ;; esac
case "$remote_repo" in /*) ;; *) echo "--remote-repo must be absolute" >&2; exit 2 ;; esac
[ "$#" -gt 0 ] || { echo "a command argv is required after --" >&2; exit 2; }

root="$(git rev-parse --show-toplevel)"
head="$(git -C "$root" rev-parse HEAD)"
git -C "$root" diff --quiet
git -C "$root" diff --cached --quiet
[ -z "$(git -C "$root" ls-files --others --exclude-standard)" ] || {
  echo "local repository has untracked files; commit them before remote execution" >&2
  exit 3
}

ssh -- "$host" bash -s -- "$remote_repo" "$head" "$@" <<'REMOTE'
set -euo pipefail
repo=$1 expected=$2
shift 2
git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  echo "remote repository is unavailable: $repo" >&2
  exit 4
}
[ -z "$(git -C "$repo" status --porcelain)" ] || { echo "remote repository is dirty" >&2; exit 5; }
actual="$(git -C "$repo" rev-parse HEAD)"
[ "$actual" = "$expected" ] || {
  echo "remote HEAD mismatch: expected $expected, observed $actual" >&2
  exit 6
}
cd -- "$repo"
exec -- "$@"
REMOTE
