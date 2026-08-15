#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/remote-exec.sh --host <ssh-host> --remote-repo <absolute-path> -- <command> [args...]

Run on a provisioned Ubuntu server only when both repositories are clean and
point at the same exact commit. No worktree or credentials are copied.
EOF
}

# OpenSSH does not transmit an argv array. The client joins every remote-command
# argument with a single space and the remote login shell parses the resulting
# string before the receiver below is reached. Passing "$@" straight to ssh
# therefore re-splits any argument containing whitespace, and a `;` or `|` in an
# argument starts a SECOND remote command that runs outside every check in this
# script -- including after a HEAD mismatch has already aborted the first one.
#
# Quote each field exactly once here, in the POSIX single-quote form every
# supported login shell understands, so that one remote parse reconstructs the
# original argv instead of reinterpreting it. This is the opposite of an eval:
# it makes the remote shell's parse a lossless identity transform.
rldyour::remote_exec::shquote() {
  local arg out=''
  for arg in "$@"; do
    out+=" '${arg//\'/\'\\\'\'}'"
  done
  printf '%s' "${out# }"
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
# Defence in depth behind the quoting above: the destination is charset-checked,
# so the repository path must be too. A shell metacharacter here can only become
# dangerous if the quoting ever regresses, and this check makes that regression
# fail closed instead of silently executing. Spaces stay legal -- they are a
# normal path character and the quoting handles them.
case "$remote_repo" in
  *[\;\&\|\$\`\'\"\\\<\>\(\)\!\*\?]* | *[$'\n\r\t']*)
    echo "unsafe remote repository path" >&2
    exit 2
    ;;
esac
[ "$#" -gt 0 ] || { echo "a command argv is required after --" >&2; exit 2; }

root="$(git rev-parse --show-toplevel)"
head="$(git -C "$root" rev-parse HEAD)"
git -C "$root" diff --quiet || {
  echo "local repository has unstaged changes; commit them before remote execution" >&2
  exit 3
}
git -C "$root" diff --cached --quiet || {
  echo "local repository has staged changes; commit them before remote execution" >&2
  exit 3
}
[ -z "$(git -C "$root" ls-files --others --exclude-standard)" ] || {
  echo "local repository has untracked files; commit them before remote execution" >&2
  exit 3
}

ssh -- "$host" bash -s -- \
  "$(rldyour::remote_exec::shquote "$remote_repo" "$head" "$@")" <<'REMOTE'
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
