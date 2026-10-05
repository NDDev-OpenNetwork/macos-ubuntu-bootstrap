#!/usr/bin/env bash
set -euo pipefail

command_name=${1:-show}
case "$command_name" in
  show)
    cat <<'EOF'
Authentication is owner-controlled and happens after installation:

1. GitHub CLI: gh auth login
2. Codex CLI: codex login
3. Claude Code: claude (follow the vendor sign-in flow)
4. Grok Build: grok login
5. Antigravity, Cursor, OpenCode and Pi: use each vendor's interactive sign-in
6. GoDaddy CLI: gddy auth login
7. Desktop applications: launch and sign in interactively where desired

The bootstrap never reads, prints, stores, or transfers credentials.
EOF
    ;;
  check)
    for cmd in gh agy claude codex cursor-agent grok opencode pi gddy; do
      if command -v "$cmd" >/dev/null 2>&1; then
        printf '[ok] %s installed\n' "$cmd"
      else
        printf '[missing] %s\n' "$cmd"
      fi
    done
    ;;
  *)
    echo "Usage: scripts/auth-handoff.sh [show|check]" >&2
    exit 2
    ;;
esac
