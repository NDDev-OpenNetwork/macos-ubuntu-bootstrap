#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APPLY=0
PLATFORM="auto"
PROFILE="auto"
GUI_MODE="auto"
DOCKER_MODE="auto"
STRICT=0
SKIP_SYSTEM=0
SKIP_AI=0
SKIP_LSPS=0
SKIP_CHECKS=0
HARDEN_SSH=0
ENABLE_UFW=0
WITH_FAIL2BAN=0

usage() {
  cat <<'EOF'
Usage: scripts/bootstrap.sh [--platform macos|ubuntu] [--profile desktop|desktop-builds|server]
                           [--gui|--no-gui] [--docker-mode none|rootful|rootless]
                           [--apply|--plan] [--skip-system] [--skip-ai]
                           [--skip-lsps] [--skip-checks] [--strict]
                           [--harden-ssh] [--enable-ufw] [--with-fail2ban]

Entrypoint for the module installer.

Default:
  - mode: plan (dry-run)
  - platform: auto-detect (darwin -> macos, linux -> ubuntu)
  - profile: macOS resolves to desktop; Ubuntu requires an explicit profile
  - GUI: enabled for desktop/desktop-builds, disabled for server
  - Docker: rootful on Ubuntu server/desktop-builds, none on desktop; rootless is explicit

Profiles:
  - desktop:        source editing, LSP/quality tools, AI CLIs, mandatory headless
                    CloakBrowser, and optional GUI apps. No Docker or project runtime.
  - desktop-builds: Ubuntu-only — everything desktop has, PLUS Docker rootful for
                    local builds/tests. Receives the server Docker layer without the
                    server baseline (no openssh-server, unattended-upgrades, or chrony).
  - server:         Ubuntu-only headless build/runtime host with Docker, AI CLIs,
                    LSPs, mandatory CloakBrowser, and safe server verification.

Safety:
  --harden-ssh and --enable-ufw are never implied. They require an explicit
  apply run because a generic remote-host mutation can lock out SSH or expose
  Docker-published ports. Plan mode remains the default.

EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --platform)
      PLATFORM="${2:?--platform requires one of macos|ubuntu}"
      shift 2
      ;;
    --profile)
      PROFILE="${2:?--profile requires one of desktop|desktop-builds|server}"
      shift 2
      ;;
    --gui)
      GUI_MODE="enabled"
      shift
      ;;
    --no-gui)
      GUI_MODE="disabled"
      shift
      ;;
    --docker-mode)
      DOCKER_MODE="${2:?--docker-mode requires one of none|rootful|rootless}"
      shift 2
      ;;
    --apply)
      APPLY=1
      shift
      ;;
    --plan | --dry-run)
      APPLY=0
      shift
      ;;
    --skip-system)
      SKIP_SYSTEM=1
      shift
      ;;
    --skip-ai)
      SKIP_AI=1
      shift
      ;;
    --skip-lsps)
      SKIP_LSPS=1
      shift
      ;;
    --skip-browser)
      echo "--skip-browser is unsupported: CloakBrowser is mandatory and has no stock-browser fallback" >&2
      exit 2
      ;;
    --skip-checks)
      SKIP_CHECKS=1
      shift
      ;;
    --strict)
      STRICT=1
      shift
      ;;
    --harden-ssh)
      HARDEN_SSH=1
      shift
      ;;
    --enable-ufw)
      ENABLE_UFW=1
      shift
      ;;
    --with-fail2ban)
      WITH_FAIL2BAN=1
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ "$PLATFORM" = "auto" ]; then
  case "$(uname -s)" in
    Darwin)
      PLATFORM="macos"
      ;;
    Linux)
      PLATFORM="ubuntu"
      ;;
    *)
      echo "Unsupported OS: $(uname -s)" >&2
      exit 2
      ;;
  esac
fi

if [ "$PLATFORM" != "macos" ] && [ "$PLATFORM" != "ubuntu" ]; then
  echo "Unsupported platform: $PLATFORM (expected macos|ubuntu)" >&2
  exit 2
fi

# Resolve the install profile. macOS is always a desktop workstation. Ubuntu
# cannot safely infer desktop/no-GUI desktop/server from uname alone, so its
# role is intentionally explicit before even a plan is composed.
if [ "$PROFILE" = "auto" ]; then
  if [ "$PLATFORM" = "macos" ]; then
    PROFILE="desktop"
  else
    echo "Ubuntu requires --profile desktop|desktop-builds|server; the bootstrap never infers Docker/server state" >&2
    exit 2
  fi
fi

if [ "$PROFILE" != "server" ] && [ "$PROFILE" != "desktop" ] && [ "$PROFILE" != "desktop-builds" ]; then
  echo "Unsupported profile: $PROFILE (expected desktop|desktop-builds|server)" >&2
  exit 2
fi

# macOS is always a desktop workstation; server/desktop-builds are meaningless there.
if [ "$PLATFORM" = "macos" ] && [ "$PROFILE" != "desktop" ]; then
  echo "macOS only supports the desktop profile (got: $PROFILE)" >&2
  exit 2
fi
# desktop-builds is Ubuntu-only (it installs Docker Engine, which this bootstrap
# never provisions on macOS).
if [ "$PLATFORM" = "macos" ] && [ "$PROFILE" = "desktop-builds" ]; then
  echo "The desktop-builds profile is Ubuntu-only; use --profile desktop on macOS" >&2
  exit 2
fi

if [ "$GUI_MODE" = "auto" ]; then
  if [ "$PROFILE" = "server" ]; then GUI_MODE="disabled"; else GUI_MODE="enabled"; fi
fi
if [ "$GUI_MODE" != "enabled" ] && [ "$GUI_MODE" != "disabled" ]; then
  echo "Unsupported GUI mode: $GUI_MODE" >&2
  exit 2
fi
if [ "$PROFILE" = "server" ] && [ "$GUI_MODE" != "disabled" ]; then
  echo "The server profile is always headless; use --profile desktop for GUI apps" >&2
  exit 2
fi

if [ "$DOCKER_MODE" = "auto" ]; then
  if [ "$PLATFORM" = "ubuntu" ] && { [ "$PROFILE" = "server" ] || [ "$PROFILE" = "desktop-builds" ]; }; then
    DOCKER_MODE="rootful"
  else
    DOCKER_MODE="none"
  fi
fi
case "$DOCKER_MODE" in none|rootful|rootless) ;; *)
  echo "Unsupported Docker mode: $DOCKER_MODE (expected none|rootful|rootless)" >&2
  exit 2
  ;;
esac
# The plain desktop profile is source/LSP-only and cannot install Docker.
# desktop-builds and server are the only profiles that may carry a Docker mode.
if [ "$PROFILE" = "desktop" ] && [ "$DOCKER_MODE" != "none" ]; then
  echo "The desktop profile is source/LSP-only; use --profile desktop-builds for local Docker" >&2
  exit 2
fi
if [ "$PLATFORM" = "macos" ] && [ "$DOCKER_MODE" != "none" ]; then
  echo "This bootstrap never installs local Docker on macOS" >&2
  exit 2
fi
if [ "$PROFILE" != "server" ] && { [ "$HARDEN_SSH" -eq 1 ] || [ "$ENABLE_UFW" -eq 1 ] || [ "$WITH_FAIL2BAN" -eq 1 ]; }; then
  echo "Server hardening flags require --profile server" >&2
  exit 2
fi

RUNNER_SCRIPT="${SCRIPT_DIR}/${PLATFORM}/install.sh"
if [ ! -x "$RUNNER_SCRIPT" ]; then
  echo "Missing runner script: $RUNNER_SCRIPT" >&2
  exit 2
fi

export RLDYOUR_DRY_RUN=$((1 - APPLY))
export RLDYOUR_PROFILE=$PROFILE
if [ "$GUI_MODE" = "enabled" ]; then
  export RLDYOUR_GUI_ENABLED=1
else
  export RLDYOUR_GUI_ENABLED=0
fi
export RLDYOUR_DOCKER_MODE=$DOCKER_MODE
export RLDYOUR_STRICT=$STRICT
export RLDYOUR_SKIP_SYSTEM=$SKIP_SYSTEM
export RLDYOUR_SKIP_AI=$SKIP_AI
export RLDYOUR_SKIP_LSPS=$SKIP_LSPS
export RLDYOUR_BROWSER_REQUIRED=1
export RLDYOUR_SKIP_CHECKS=$SKIP_CHECKS
export RLDYOUR_HARDEN_SSH=$HARDEN_SSH
export RLDYOUR_ENABLE_UFW=$ENABLE_UFW
export RLDYOUR_WITH_FAIL2BAN=$WITH_FAIL2BAN
if [ "$PROFILE" = "desktop" ]; then
  export RLDYOUR_LOCAL_EXECUTION_POLICY="source-lsp-only"
elif [ "$PROFILE" = "desktop-builds" ]; then
  export RLDYOUR_LOCAL_EXECUTION_POLICY="local-dev-with-builds"
else
  export RLDYOUR_LOCAL_EXECUTION_POLICY="container-execution-only"
fi

"$RUNNER_SCRIPT"
