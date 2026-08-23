#!/usr/bin/env bash
# Managed by macos-ubuntu-bootstrap: herdr-oom-guard-v1
#
# systemd-oomd kills a whole leaf cgroup. Ptyxis launches Herdr inside one
# transient scope, so every agent, MCP server and language server dies with the
# multiplexer. This guard keeps Herdr and the agent CLIs in that cgroup, moves
# MCP/LSP processes into herdr-reclaim.service (a sibling unit oomd may kill),
# and marks the Herdr unit ManagedOOMPreference=omit.
set -euo pipefail

HERDR_OOM_GUARD_MARKER="# Managed by macos-ubuntu-bootstrap: herdr-oom-guard-v1"
HERDR_RECLAIM_UNIT="${HERDR_RECLAIM_UNIT:-herdr-reclaim.service}"
HERDR_OOM_TICK_SEC="${HERDR_OOM_TICK_SEC:-3}"
HERDR_RECLAIM_OOM_SCORE="${HERDR_RECLAIM_OOM_SCORE:-800}"
# systemd-oomd trips at 50% for 20s on user@.service. Shed MCP/LSP earlier so
# pressure falls before oomd picks some other leaf (Chrome, gnome-shell).
HERDR_OOM_PRESSURE_LIMIT="${HERDR_OOM_PRESSURE_LIMIT:-25}"
HERDR_OOM_PRESSURE_TICKS="${HERDR_OOM_PRESSURE_TICKS:-3}"
HERDR_OOM_PRESSURE_STREAK=0

rldyour::herdr_oom::log() {
  printf 'herdr-oom-guard: %s\n' "$*"
}

rldyour::herdr_oom::classify() {
  # stdout: protect | reclaim
  local cmdline=$1
  local comm=${2:-}
  local lc

  case "$comm" in
    herdr|ptyxis|ptyxis-agent|claude|codex|grok)
      printf '%s\n' protect
      return 0
      ;;
  esac

  lc=${cmdline,,}
  case "$lc" in
    *'/herdr server'*|'herdr server'*|*' herdr server'*)
      printf '%s\n' protect
      return 0
      ;;
    *'claude --resume'*|*'claude --print'*|*'codex resume'*|*'/bin/grok'*)
      printf '%s\n' protect
      return 0
      ;;
  esac

  case "$lc" in
    *context7-mcp*|*chrome-devtools-mcp*|*sequential-thinking*|*modelcontextprotocol*)
      printf '%s\n' reclaim
      return 0
      ;;
    *mcp-server*|*'/mcp/'*|*shadcn@*|*shadcn*mcp*)
      printf '%s\n' reclaim
      return 0
      ;;
    *language_servers*|*tsserver.js*|*language-server*|*pyright-langserver*)
      printf '%s\n' reclaim
      return 0
      ;;
    *pyright*|*marksman*|*rust-analyzer*|*gopls*|*clangd*|*analysis_server*|*taplo*)
      printf '%s\n' reclaim
      return 0
      ;;
  esac

  case "$comm" in
    bash|zsh|fish|sh|dash)
      printf '%s\n' protect
      return 0
      ;;
  esac

  printf '%s\n' protect
}

rldyour::herdr_oom::read_cmdline() {
  local pid=$1
  tr '\0' ' ' <"/proc/${pid}/cmdline" 2>/dev/null || true
}

rldyour::herdr_oom::read_comm() {
  local pid=$1
  tr -d '\0\n' <"/proc/${pid}/comm" 2>/dev/null || true
}

rldyour::herdr_oom::server_pid() {
  local dir pid cmd
  shopt -s nullglob
  for dir in /proc/[0-9]*; do
    pid=${dir#/proc/}
    [ -r "${dir}/cmdline" ] || continue
    cmd=$(tr '\0' ' ' <"${dir}/cmdline" 2>/dev/null || true)
    case "$cmd" in
      *'/herdr server'*|'herdr server'*)
        printf '%s\n' "$pid"
        shopt -u nullglob
        return 0
        ;;
    esac
  done
  shopt -u nullglob
  return 0
}

rldyour::herdr_oom::cgroup_dir() {
  local pid=$1 rel
  rel=$(awk -F: '{ print $NF }' "/proc/${pid}/cgroup" 2>/dev/null) || return 1
  [ -n "$rel" ] || return 1
  printf '%s\n' "/sys/fs/cgroup${rel}"
}

rldyour::herdr_oom::unit_of_pid() {
  local pid=$1 rel
  rel=$(awk -F: '{ print $NF }' "/proc/${pid}/cgroup" 2>/dev/null) || return 1
  printf '%s\n' "${rel##*/}"
}

rldyour::herdr_oom::cgroup_pids() {
  local cg=$1
  [ -r "${cg}/cgroup.procs" ] || return 0
  tr -s '[:space:]' '\n' <"${cg}/cgroup.procs" | grep -E '^[0-9]+$' || true
}

rldyour::herdr_oom::ensure_reclaim() {
  systemctl --user start "$HERDR_RECLAIM_UNIT"
}

rldyour::herdr_oom::omit_unit() {
  local unit=$1
  [ -n "$unit" ] || return 0
  case "$unit" in
    "$HERDR_RECLAIM_UNIT"|herdr-oom-guard.service|user@*.service|init.scope)
      return 0
      ;;
  esac
  systemctl --user set-property --runtime "$unit" ManagedOOMPreference=omit
}

rldyour::herdr_oom::attach_batch() {
  local unit=$1
  shift
  [ "$#" -gt 0 ] || return 0
  if busctl --user call org.freedesktop.systemd1 /org/freedesktop/systemd1 \
    org.freedesktop.systemd1.Manager AttachProcessesToUnit ssau \
    "$unit" "/" "$#" "$@" >/dev/null; then
    return 0
  fi
  local dest_cg pid
  dest_cg="$(systemctl --user show "$unit" -p ControlGroup --value 2>/dev/null || true)"
  if [ -z "$dest_cg" ] || [ ! -w "/sys/fs/cgroup${dest_cg}/cgroup.procs" ]; then
    rldyour::herdr_oom::log "attach batch to ${unit} failed"
    return 1
  fi
  for pid in "$@"; do
    printf '%s\n' "$pid" >"/sys/fs/cgroup${dest_cg}/cgroup.procs" 2>/dev/null || \
      rldyour::herdr_oom::log "cgroup.procs attach failed pid=${pid} unit=${unit}"
  done
}

rldyour::herdr_oom::attach() {
  local unit=$1
  shift
  [ "$#" -gt 0 ] || return 0
  local pid batch=() failed=0
  for pid in "$@"; do
    batch+=("$pid")
    if [ "${#batch[@]}" -ge 40 ]; then
      rldyour::herdr_oom::attach_batch "$unit" "${batch[@]}" || failed=1
      batch=()
    fi
  done
  if [ "${#batch[@]}" -gt 0 ]; then
    rldyour::herdr_oom::attach_batch "$unit" "${batch[@]}" || failed=1
  fi
  return "$failed"
}

rldyour::herdr_oom::raise_oom_score() {
  local pid=$1
  printf '%s\n' "$HERDR_RECLAIM_OOM_SCORE" >"/proc/${pid}/oom_score_adj" 2>/dev/null || true
}

rldyour::herdr_oom::pressure_avg10() {
  local file=$1 line
  [ -r "$file" ] || return 1
  line=$(awk '/^some / { print; exit }' "$file") || return 1
  [ -n "$line" ] || return 1
  printf '%s\n' "$line" | tr ' ' '\n' | awk -F= '$1 == "avg10" { print $2; exit }'
}

rldyour::herdr_oom::pressure_file() {
  local uid
  uid=$(id -u)
  if [ -r "/sys/fs/cgroup/user.slice/user-${uid}.slice/user@${uid}.service/memory.pressure" ]; then
    printf '%s\n' "/sys/fs/cgroup/user.slice/user-${uid}.slice/user@${uid}.service/memory.pressure"
    return 0
  fi
  if [ -r /proc/pressure/memory ]; then
    printf '%s\n' /proc/pressure/memory
    return 0
  fi
  return 1
}

rldyour::herdr_oom::shed_reclaim() {
  local dest_cg n
  dest_cg="$(systemctl --user show "$HERDR_RECLAIM_UNIT" -p ControlGroup --value 2>/dev/null || true)"
  [ -n "$dest_cg" ] || return 0
  n=$(rldyour::herdr_oom::cgroup_pids "/sys/fs/cgroup${dest_cg}" | grep -c . || true)
  if [ "${n:-0}" -le 1 ]; then
    return 0
  fi
  rldyour::herdr_oom::log "shedding ${n} reclaim pids under memory pressure"
  if [ -w "/sys/fs/cgroup${dest_cg}/cgroup.kill" ]; then
    printf '1\n' >"/sys/fs/cgroup${dest_cg}/cgroup.kill"
    return 0
  fi
  systemctl --user kill --kill-whom=all --signal=SIGKILL "$HERDR_RECLAIM_UNIT" || true
}

rldyour::herdr_oom::tick() {
  local server_pid unit cg pid cmdline comm class reclaim_cg pressure_file avg10
  local -a reclaim_pids=()
  local -a rescue_pids=()

  server_pid="$(rldyour::herdr_oom::server_pid)"
  [ -n "${server_pid:-}" ] || return 0
  [ -d "/proc/${server_pid}" ] || return 0

  rldyour::herdr_oom::ensure_reclaim

  unit="$(rldyour::herdr_oom::unit_of_pid "$server_pid")"
  cg="$(rldyour::herdr_oom::cgroup_dir "$server_pid")"
  [ -n "$unit" ] && [ -n "$cg" ] || return 0

  if [ "$unit" = "$HERDR_RECLAIM_UNIT" ]; then
    rldyour::herdr_oom::log "herdr server is in ${HERDR_RECLAIM_UNIT}; refusing to reclaim that unit"
    return 0
  fi

  rldyour::herdr_oom::omit_unit "$unit"

  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    [ "$pid" != "$server_pid" ] || continue
    cmdline="$(rldyour::herdr_oom::read_cmdline "$pid")"
    comm="$(rldyour::herdr_oom::read_comm "$pid")"
    class="$(rldyour::herdr_oom::classify "$cmdline" "$comm")"
    if [ "$class" = reclaim ]; then
      reclaim_pids+=("$pid")
    fi
  done < <(rldyour::herdr_oom::cgroup_pids "$cg")

  if [ "${#reclaim_pids[@]}" -gt 0 ]; then
    if rldyour::herdr_oom::attach "$HERDR_RECLAIM_UNIT" "${reclaim_pids[@]}"; then
      for pid in "${reclaim_pids[@]}"; do
        rldyour::herdr_oom::raise_oom_score "$pid"
      done
      rldyour::herdr_oom::log "moved ${#reclaim_pids[@]} mcp/lsp pids to ${HERDR_RECLAIM_UNIT} (herdr unit=${unit} pid=${server_pid})"
    else
      rldyour::herdr_oom::log "failed to move ${#reclaim_pids[@]} mcp/lsp pids to ${HERDR_RECLAIM_UNIT}"
    fi
  fi

  reclaim_cg="$(systemctl --user show "$HERDR_RECLAIM_UNIT" -p ControlGroup --value 2>/dev/null || true)"
  if [ -n "$reclaim_cg" ] && [ -d "/sys/fs/cgroup${reclaim_cg}" ]; then
    while IFS= read -r pid; do
      [ -n "$pid" ] || continue
      cmdline="$(rldyour::herdr_oom::read_cmdline "$pid")"
      comm="$(rldyour::herdr_oom::read_comm "$pid")"
      case "$comm" in
        herdr|ptyxis|ptyxis-agent|claude|codex|grok)
          rescue_pids+=("$pid")
          ;;
      esac
    done < <(rldyour::herdr_oom::cgroup_pids "/sys/fs/cgroup${reclaim_cg}")
  fi
  if [ "${#rescue_pids[@]}" -gt 0 ] && [ -n "$unit" ]; then
    rldyour::herdr_oom::attach "$unit" "${rescue_pids[@]}"
    rldyour::herdr_oom::log "rescued ${#rescue_pids[@]} protected pids back to ${unit}"
  fi

  pressure_file="$(rldyour::herdr_oom::pressure_file || true)"
  avg10="0"
  if [ -n "$pressure_file" ]; then
    avg10="$(rldyour::herdr_oom::pressure_avg10 "$pressure_file" || printf '0\n')"
  fi
  if awk -v n="$avg10" -v lim="$HERDR_OOM_PRESSURE_LIMIT" 'BEGIN { exit !(n+0 >= lim+0) }'; then
    HERDR_OOM_PRESSURE_STREAK=$((HERDR_OOM_PRESSURE_STREAK + 1))
    rldyour::herdr_oom::log "memory pressure avg10=${avg10} streak=${HERDR_OOM_PRESSURE_STREAK}/${HERDR_OOM_PRESSURE_TICKS}"
    if [ "$HERDR_OOM_PRESSURE_STREAK" -ge "$HERDR_OOM_PRESSURE_TICKS" ]; then
      rldyour::herdr_oom::shed_reclaim
      HERDR_OOM_PRESSURE_STREAK=0
    fi
  else
    HERDR_OOM_PRESSURE_STREAK=0
  fi
}

rldyour::herdr_oom::main() {
  rldyour::herdr_oom::log "starting (${HERDR_OOM_GUARD_MARKER})"
  while true; do
    rldyour::herdr_oom::tick || rldyour::herdr_oom::log "tick failed: $?"
    sleep "$HERDR_OOM_TICK_SEC"
  done
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  rldyour::herdr_oom::main "$@"
fi
