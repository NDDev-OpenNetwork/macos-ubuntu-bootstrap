"""Herdr systemd-oomd isolation: classify MCP/LSP away from the multiplexer."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts/lib/herdr-oom-guard.sh"
RECLAIM = ROOT / "templates/systemd/user/herdr-reclaim.service"
GUARD_UNIT = ROOT / "templates/systemd/user/herdr-oom-guard.service"
DESKTOP = ROOT / "templates/desktop/herdr.desktop"
INSTALL = ROOT / "scripts/ubuntu/install.sh"
VERIFY = ROOT / "scripts/ubuntu/verify.sh"


def classify(cmdline: str, comm: str = "") -> str:
    script = r"""
source "$1"
rldyour::herdr_oom::classify "$2" "$3"
"""
    result = subprocess.run(
        ["bash", "-c", script, "herdr-oom-classify", str(GUARD), cmdline, comm],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return result.stdout.strip()


@pytest.mark.parametrize(
    ("cmdline", "comm"),
    [
        ("/home/rldyourmnd/.local/share/rldyour/herdr/0.7.5/herdr server", "herdr"),
        ("herdr", "herdr"),
        ("claude --resume f8b842ec-fa63-4275-9b18-83505401d421", "claude"),
        ("codex resume 01a01d26-30dc-7ad3-bd8a-417396ea6f54", "codex"),
        ("grok", "grok"),
        ("/usr/bin/ptyxis --new-window --title Herdr", "ptyxis"),
        ("/bin/bash", "bash"),
        ("uv run --locked pytest -n 4", "uv"),
        ("/home/rldyourmnd/Developer/guild/ai_stp/.venv/bin/python -u -c import sys", "python"),
    ],
)
def test_protects_herdr_agents_and_user_work(cmdline: str, comm: str) -> None:
    assert classify(cmdline, comm) == "protect"


@pytest.mark.parametrize(
    ("cmdline", "comm"),
    [
        ("node /tmp/bunx-1000-@upstash/context7-mcp@3.2.3/node_modules/.bin/context7-mcp", "node"),
        ("chrome-devtools-mcp", "chrome-devtools-"),
        ("node /tmp/bunx-1000-@modelcontextprotocol/server-sequential-thinking@2026.7.4/node_modules/.bin/mcp-server-sequential-thinking", "node"),
        ("node /tmp/bunx-1000-shadcn@4.13.0/node_modules/.bin/shadcn mcp", "node"),
        ("node ./mcp/server.cjs --stdio", "node"),
        ("/home/rldyourmnd/.local/bin/node .../pyright/dist/langserver.index.js -- --stdio", "node"),
        ("node .../typescript/lib/tsserver.js --stdio", "node"),
        ("node .../typescript-language-server --stdio", "node"),
        ("node .../bash-language-server start", "node"),
        ("node .../yaml-language-server --stdio", "node"),
        ("/home/rldyourmnd/.serena/language_servers/static/Marksman/marksman server", "marksman"),
        ("dart mcp-server --force-roots-fallback", "dart"),
        ("rust-analyzer", "rust-analyzer"),
        ("gopls", "gopls"),
    ],
)
def test_reclaims_mcp_and_lsp(cmdline: str, comm: str) -> None:
    assert classify(cmdline, comm) == "reclaim"


def test_agent_comm_wins_over_mcp_like_cmdline() -> None:
    assert (
        classify(
            "claude --resume abc node /tmp/bunx-1000-context7-mcp",
            "claude",
        )
        == "protect"
    )


def test_shell_wrappers_of_lsp_are_reclaimed() -> None:
    assert (
        classify(
            "/bin/sh -c /home/rldyourmnd/.local/bin/uvx -p 3.13 --from pyright==1.1.403 pyright-langserver --stdio",
            "sh",
        )
        == "reclaim"
    )
    assert classify("bunx shadcn@4.13.0 mcp", "bunx") == "reclaim"


def test_pressure_avg10_parser(tmp_path: Path) -> None:
    pressure = tmp_path / "memory.pressure"
    pressure.write_text(
        "some avg10=41.50 avg60=12.00 avg300=4.00 total=9\n"
        "full avg10=10.00 avg60=1.00 avg300=0.00 total=1\n",
        encoding="utf-8",
    )
    script = r"""
source "$1"
rldyour::herdr_oom::pressure_avg10 "$2"
"""
    result = subprocess.run(
        ["bash", "-c", script, "pressure", str(GUARD), str(pressure)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "41.50"


def test_units_split_oomd_preference() -> None:
    reclaim = RECLAIM.read_text(encoding="utf-8")
    guard = GUARD_UNIT.read_text(encoding="utf-8")
    assert "ManagedOOMPreference=none" in reclaim
    assert "Delegate=cpu memory pids" in reclaim
    assert "ManagedOOMPreference=omit" in guard
    assert "Requires=herdr-reclaim.service" not in guard
    assert "Wants=herdr-reclaim.service" in guard
    assert "herdr-oom-guard-unit-v1" in reclaim
    assert "herdr-oom-guard-unit-v1" in guard
    assert "ExecStart=/bin/sleep infinity" in reclaim


def test_guard_script_is_sourceable_and_marked() -> None:
    text = GUARD.read_text(encoding="utf-8")
    assert "herdr-oom-guard-v1" in text
    assert 'if [ "${BASH_SOURCE[0]}" = "$0" ]; then' in text
    result = subprocess.run(
        ["bash", "-n", str(GUARD)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_desktop_starts_guard_before_herdr() -> None:
    text = DESKTOP.read_text(encoding="utf-8")
    assert "desktop-entry-herdr-v2" in text
    assert "Exec=ptyxis" in text
    assert "herdr-oom-guard.service" in text
    assert "exec herdr" in text


def test_installer_and_verifier_own_the_guard() -> None:
    installer = INSTALL.read_text(encoding="utf-8")
    verifier = VERIFY.read_text(encoding="utf-8")
    assert "rldyour::ubuntu::install_herdr_oom_guard" in installer
    assert "rldyour::ubuntu_verify::herdr_oom_guard" in verifier
    assert "install_herdr_oom_guard" in installer.split("main() {", 1)[1]


def test_guard_skips_systemd_enable_when_home_is_not_login_home() -> None:
    """Installer tests override HOME; they must not talk to the live user systemd."""
    installer = INSTALL.read_text(encoding="utf-8")
    assert "login_home" in installer
    assert "HOME is not the login home" in installer
