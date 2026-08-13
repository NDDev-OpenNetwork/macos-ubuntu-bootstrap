from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/bootstrap.sh", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_contract_and_version_match() -> None:
    contract = json.loads((ROOT / "config/rldyour-contract.json").read_text())
    assert contract["adapter"]["version"] == (ROOT / "VERSION").read_text().strip()
    assert contract["harnesses"]["active"] == ["codex", "claude-code", "grok-build"]
    assert "browser_automation" not in contract


def test_plan_matrix() -> None:
    cases = [
        ("--platform", "macos", "--no-gui"),
        ("--platform", "ubuntu", "--profile", "desktop", "--no-gui"),
        ("--platform", "ubuntu", "--profile", "desktop-builds", "--no-gui"),
        ("--platform", "ubuntu", "--profile", "server"),
    ]
    for args in cases:
        result = run(*args, "--skip-system", "--skip-ai", "--skip-lsps", "--skip-checks")
        assert result.returncode == 0, result.stdout + result.stderr


def test_ai_plan_names_three_vendor_clis() -> None:
    result = run("--platform", "macos", "--no-gui", "--skip-system", "--skip-lsps", "--skip-checks")
    assert result.returncode == 0
    assert "Codex, Claude Code, Grok Build" in result.stdout


def test_unrestricted_launchers_use_vendor_flags() -> None:
    common = (ROOT / "scripts/lib/common.sh").read_text()
    assert 'codex --dangerously-bypass-approvals-and-sandbox' in common
    assert 'claude --dangerously-skip-permissions' in common
    assert 'grok --permission-mode bypassPermissions --always-approve' in common


def test_codex_install_uses_receipt_bound_ubuntu_npm_without_publishing_it() -> None:
    common = (ROOT / "scripts/lib/common.sh").read_text()
    assert '$HOME/.local/share/rldyour/node/v24.18.0/bin/npm' in common
    assert '"$npm_bin" install --global' in common


def test_ubuntu_profile_is_explicit() -> None:
    result = run("--platform", "ubuntu")
    assert result.returncode == 2
    assert "requires --profile" in result.stderr


# ----------------------------- plan is read-only -----------------------------


@pytest.mark.parametrize(
    "profile,gui",
    [("server", []), ("desktop", ["--no-gui"]), ("desktop-builds", ["--no-gui"])],
)
def test_plan_creates_nothing_in_the_home_it_describes(
    tmp_path: Path, profile: str, gui: list[str]
) -> None:
    """`--plan` is documented as read-only; prove it against a throwaway HOME.

    A plan used to create ~/.local/bin from an unconditional mkdir, and both
    ~/.bun/install/global and ~/.cache/uv because the "is this pin already
    installed?" probes are package-manager commands that initialize their own
    store before they can answer.
    """
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        ["bash", "scripts/bootstrap.sh", "--platform", "ubuntu",
         "--profile", profile, *gui, "--plan"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "HOME": str(home)},
    )
    # rldyour::log writes to stdout, so a failure explains itself there.
    assert result.returncode == 0, (result.stdout + result.stderr)[-3000:]
    created = sorted(str(path.relative_to(home)) for path in home.rglob("*"))
    assert created == [], f"plan mutated the home directory: {created}"
