#!/usr/bin/env bash
#
# scripts/ubuntu/open-design.sh
# ------------------------------------------------------------
# Open Design install layer — the first docker-compose workload in this
# module. Gated behind an explicit operator opt-in
# (--install-open-design / RLDYOUR_INSTALL_OPEN_DESIGN=1).
#
# Why this is a separate, opt-in layer:
#   Open Design (https://github.com/nexu-io/open-design) publishes NO native
#   Linux builds (macOS .dmg / Windows .exe only). On Linux it runs via the
#   published Docker image ghcr.io/nexu-io/od.
#
#   The baseline contract forbids Docker on the desktop profile
#   (source-lsp-only) and never runs containers on any profile (server.sh
#   only INSTALLS Docker). This layer deliberately does NOT relax either
#   policy. Instead it:
#     - on desktop: REQUIRES Docker to already be present (preflight only,
#       never installs Docker itself);
#     - on server:  relies on Docker installed by the server layer earlier;
#     - never adds the user to the docker group (never-automatic preserved);
#       it reaches the daemon via `sg docker` when direct socket access is
#       denied, leaving group membership exactly as the operator set it.
#
# Idempotent, dry-run safe (all mutations go through rldyour::run), and
# records an open-design-v1 managed marker receipt so device_integrity can
# see it.
# ------------------------------------------------------------

set -euo pipefail

# Defaults — overridable via environment for non-default ports/repos/targets.
: "${RLDYOUR_OPENDESIGN_REPO:=https://github.com/NDDev-it-com/open-design.git}"
: "${RLDYOUR_OPENDESIGN_TARGET:=${HOME}/Developer/forks/open-design}"
: "${RLDYOUR_OPENDESIGN_PORT:=7456}"
: "${RLDYOUR_OPENDESIGN_IMAGE:=ghcr.io/nexu-io/od:latest}"
OPENDESIGN_RECEIPT_NAME="open-design-v1"
OPENDESIGN_RECEIPT_DIR="${XDG_DATA_HOME:-${HOME}/.local/share}/rldyour/open-design"
OPENDESIGN_RECEIPT_FILE="${OPENDESIGN_RECEIPT_DIR}/${OPENDESIGN_RECEIPT_NAME}"

# Run a docker CLI invocation, transparently reaching the daemon through
# `sg docker` when the current process lacks direct socket access.
# Usage: opendesign::docker <args...>
opendesign::docker() {
  if docker >/dev/null 2>&1; then
    # Fast path: direct socket access works.
    docker "$@"
    return $?
  fi
  # Permission denied → try the docker group without changing membership.
  if command -v sg >/dev/null 2>&1 && sg docker -c "docker >/dev/null 2>&1" 2>/dev/null; then
    # shellcheck disable=SC2068
    sg docker -c "docker $*" 2>&1
    return $?
  fi
  rldyour::log "error" "cannot reach docker daemon directly or via 'sg docker' (is the user in the docker group?)"
  return 1
}

# Run `docker compose ...` through the same access wrapper. Compose subcommand
# and args are passed as a single string to `sg docker -c` when needed.
# Usage: opendesign::docker_compose <args...>
opendesign::docker_compose() {
  if docker compose >/dev/null 2>&1; then
    # Fast path: direct socket access works.
    docker compose "$@"
    return $?
  fi
  if command -v sg >/dev/null 2>&1 && sg docker -c "docker >/dev/null 2>&1" 2>/dev/null; then
    # shellcheck disable=SC2068
    sg docker -c "docker compose $*" 2>&1
    return $?
  fi
  rldyour::log "error" "cannot reach docker daemon directly or via 'sg docker' (is the user in the docker group?)"
  return 1
}

# Fail-closed preflight: Docker must exist and the daemon must be reachable.
# Never installs Docker (preserves the desktop source-lsp policy).
opendesign::preflight_docker() {
  command -v docker >/dev/null 2>&1 || {
    rldyour::log "error" "docker CLI not found. Install Docker first (server profile installs it; desktop requires a manual install). Open Design on Linux runs only via Docker."
    return 2
  }
  # Reachable directly OR via sg docker.
  if docker info >/dev/null 2>&1; then
    return 0
  fi
  if command -v sg >/dev/null 2>&1 && sg docker -c "docker info" >/dev/null 2>&1; then
    rldyour::log "info" "docker daemon reachable via 'sg docker' (direct socket denied; group membership unchanged)"
    return 0
  fi
  rldyour::log "error" "docker daemon not reachable directly or via 'sg docker'. Start the daemon or ensure group access."
  return 2
}

# Idempotent clone of the Open Design repo to the workspace target.
opendesign::ensure_checkout() {
  local repo="$RLDYOUR_OPENDESIGN_REPO"
  local target="$RLDYOUR_OPENDESIGN_TARGET"
  if [ -d "$target/.git" ]; then
    rldyour::log "info" "open-design checkout present: $target"
    if [ "$RLDYOUR_DRY_RUN" -ne 1 ]; then
      git -C "$target" fetch --quiet --prune origin || rldyour::log "warn" "fetch failed (offline? continuing with existing checkout)"
    fi
    return 0
  fi
  if [ -e "$target" ] && [ ! -d "$target/.git" ]; then
    rldyour::log "error" "target exists but is not a git checkout: $target (refusing to overwrite)"
    return 2
  fi
  rldyour::run git clone --depth 1 "$repo" "$target"
}

# Create deploy/.env from the template if absent; generate OD_API_TOKEN.
# Never overwrites an existing .env (operator edits are preserved).
opendesign::configure_env() {
  local deploy_dir="$RLDYOUR_OPENDESIGN_TARGET/deploy"
  local env_template="$deploy_dir/.env.example"
  local env_file="$deploy_dir/.env"
  if [ "$RLDYOUR_DRY_RUN" -eq 1 ]; then
    rldyour::log "info" "[DRY-RUN] copy deploy/.env.example -> deploy/.env and generate OD_API_TOKEN"
    return 0
  fi
  [ -f "$env_template" ] || {
    rldyour::log "error" "deploy/.env.example missing in checkout: $env_template"
    return 2
  }
  if [ -f "$env_file" ]; then
    rldyour::log "info" "deploy/.env already exists — preserving operator edits"
    return 0
  fi
  cp "$env_template" "$env_file"
  chmod 600 "$env_file"
  # Generate a secure token only if the template expects one.
  if grep -q '^OD_API_TOKEN=$' "$env_file"; then
    local token
    token="$(openssl rand -hex 32)"
    sed -i "s/^OD_API_TOKEN=$/OD_API_TOKEN=$token/" "$env_file"
    rldyour::log "ok" "generated OD_API_TOKEN (32-byte hex)"
  fi
  # Pin the configured port from the contract default.
  if grep -q '^OPEN_DESIGN_PORT=' "$env_file"; then
    sed -i "s/^OPEN_DESIGN_PORT=.*/OPEN_DESIGN_PORT=$RLDYOUR_OPENDESIGN_PORT/" "$env_file"
  fi
  rldyour::log "ok" "wrote $env_file"
}

# Bring the service up (base compose only — the linux override mounts host
# agent CLIs that may not exist on every device and would fail the run).
opendesign::compose_up() {
  local deploy_dir="$RLDYOUR_OPENDESIGN_TARGET/deploy"
  local env_file="$deploy_dir/.env"
  if [ "$RLDYOUR_DRY_RUN" -eq 1 ]; then
    rldyour::section "Pull image and start Open Design container (dry-run)"
    rldyour::log "info" "[DRY-RUN] docker compose -f deploy/docker-compose.yml --env-file deploy/.env pull"
    rldyour::log "info" "[DRY-RUN] docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d"
    return 0
  fi
  [ -f "$env_file" ] || { rldyour::log "error" ".env missing before compose up"; return 2; }

  rldyour::section "Pull image and start Open Design container"
  # Pull first (clear failure mode if the registry is unreachable).
  rldyour::run opendesign::docker_compose -f "$deploy_dir/docker-compose.yml" --env-file "$env_file" pull \
    || rldyour::log "warn" "compose pull reported an issue (continuing)"
  rldyour::run opendesign::docker_compose -f "$deploy_dir/docker-compose.yml" --env-file "$env_file" up -d
}

# Poll /api/health up to ~60s; report the running version.
opendesign::verify() {
  if [ "$RLDYOUR_DRY_RUN" -eq 1 ]; then
    rldyour::log "info" "[DRY-RUN] poll http://127.0.0.1:$RLDYOUR_OPENDESIGN_PORT/api/health until 200"
    return 0
  fi
  local i code body
  for i in $(seq 1 20); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${RLDYOUR_OPENDESIGN_PORT}/api/health" 2>/dev/null || true)"
    if [ "$code" = "200" ]; then
      body="$(curl -s "http://127.0.0.1:${RLDYOUR_OPENDESIGN_PORT}/api/health" 2>/dev/null || true)"
      rldyour::log "ok" "Open Design healthy: ${body:-ok} (after ~$((i*3))s)"
      return 0
    fi
    sleep 3
  done
  rldyour::log "warn" "Open Design did not report healthy within ~60s (HTTP ${code:-none}); check 'docker logs open-design'"
  return 0  # non-fatal: the container may still be starting.
}

# Write a managed marker receipt so device_integrity can see the layer.
opendesign::record_receipt() {
  if [ "$RLDYOUR_DRY_RUN" -eq 1 ]; then
    rldyour::log "info" "[DRY-RUN] write managed receipt $OPENDESIGN_RECEIPT_FILE"
    return 0
  fi
  mkdir -p "$OPENDESIGN_RECEIPT_DIR"
  {
    printf '# Managed by macos-ubuntu-bootstrap: %s\n' "$OPENDESIGN_RECEIPT_NAME"
    printf 'repo=%s\n' "$RLDYOUR_OPENDESIGN_REPO"
    printf 'target=%s\n' "$RLDYOUR_OPENDESIGN_TARGET"
    printf 'image=%s\n' "$RLDYOUR_OPENDESIGN_IMAGE"
    printf 'port=%s\n' "$RLDYOUR_OPENDESIGN_PORT"
    printf 'installed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >"$OPENDESIGN_RECEIPT_FILE"
  chmod 600 "$OPENDESIGN_RECEIPT_FILE"
  rldyour::log "ok" "receipt: $OPENDESIGN_RECEIPT_FILE"
}

# Public entry — composed, fail-closed, dry-run safe.
rldyour::ubuntu_opendesign::install() {
  rldyour::section "Open Design (Docker image, opt-in layer)"
  if [ "${RLDYOUR_INSTALL_OPEN_DESIGN:-0}" -ne 1 ]; then
    rldyour::log "info" "open-design layer disabled (enable with --install-open-design)"
    return 0
  fi
  rldyour::log "info" "profile=$RLDYOUR_PROFILE image=$RLDYOUR_OPENDESIGN_IMAGE port=$RLDYOUR_OPENDESIGN_PORT"

  opendesign::preflight_docker || return 2
  opendesign::ensure_checkout  || return 2
  opendesign::configure_env    || return 2
  opendesign::compose_up       || return 2
  opendesign::verify           || true
  opendesign::record_receipt   || true

  rldyour::section "Open Design available at http://127.0.0.1:${RLDYOUR_OPENDESIGN_PORT}"
}
