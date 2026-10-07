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
    assert contract["harnesses"]["active"] == ["antigravity", "claude-code", "codex", "cursor", "grok-build", "opencode", "pi", "devin"]
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


def test_ai_plan_names_all_eight_vendor_clis_and_godaddy() -> None:
    result = run("--platform", "macos", "--no-gui", "--skip-system", "--skip-lsps", "--skip-checks")
    assert result.returncode == 0
    for name in ["antigravity", "claude-code", "codex", "cursor", "grok-build", "opencode", "pi", "devin", "gddy"]:
        assert f"[plan] {name} " in result.stdout


def test_combined_app_mode_requires_gui_ubuntu():
    for args in [("--platform", "macos"), ("--platform", "ubuntu", "--profile", "server")]:
        result = run(*args, "--with-harness-apps")
        assert result.returncode == 2
        assert "--with-harness-apps" in result.stderr


def test_combined_plan_is_read_only_and_reports_app_module():
    result = run("--platform", "ubuntu", "--profile", "desktop", "--with-harness-apps",
                 "--skip-system", "--skip-ai", "--skip-lsps", "--skip-checks")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "harness application module plan complete" in result.stdout


def test_unrestricted_launchers_use_vendor_flags() -> None:
    common = (ROOT / "scripts/lib/common.sh").read_text()
    assert 'codex --dangerously-bypass-approvals-and-sandbox' in common
    assert 'claude --dangerously-skip-permissions' in common
    assert 'grok --permission-mode bypassPermissions --always-approve' in common


def test_vendor_cli_install_uses_verified_standalone_payloads_without_npm() -> None:
    common = (ROOT / "scripts/lib/common.sh").read_text()
    start = common.index("rldyour::install_vendor_ai_clis()")
    end = common.index("rldyour::install_ai_launchers()", start)
    block = common[start:end]
    assert 'managed_cli.py' in block
    assert '"$cli_installer" install' in block
    assert 'npm install' not in block
    assert 'bash "$claude_script"' not in block


def test_ubuntu_profile_is_explicit() -> None:
    result = run("--platform", "ubuntu")
    assert result.returncode == 2
    assert "requires --profile" in result.stderr


# ----------------------------- plan is read-only -----------------------------


@pytest.mark.parametrize(
    "extra",
    [
        ["--profile", "desktop", "--no-gui"],
        ["--profile", "server", "--docker-mode", "none"],
    ],
)
def test_plan_creates_nothing_in_the_home_it_describes(
    tmp_path: Path, extra: list[str]
) -> None:
    """`--plan` is documented as read-only; prove it against a throwaway HOME.

    A plan used to create ~/.local/bin from an unconditional mkdir, and both
    ~/.bun/install/global and ~/.cache/uv because the "is this pin already
    installed?" probes are package-manager commands that initialize their own
    store before they can answer.

    Docker-carrying compositions are excluded: install_docker_packages refuses a
    partial Docker CE package set, so their outcome depends on the host image
    rather than on plan behaviour.
    """
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        ["bash", "scripts/bootstrap.sh", "--platform", "ubuntu", *extra, "--plan"],
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


def test_macos_plan_never_invokes_homebrew(tmp_path: Path) -> None:
    """A plan states what it will converge on; it does not ask the package manager.

    The dry-run guard used to fire only when brew was absent, so on the machine
    this installer targets -- where brew is always present -- a plan ran
    `brew list` once per formula and per cask. Homebrew materializes
    ~/Library/Caches/Homebrew/bootsnap on its first call, so the plan wrote to
    the home directory it was only describing. Proven on a macOS runner by the
    read-only plan lane in scripts/ci/validate.sh.
    """
    home = tmp_path / "home"
    home.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "brew-calls"
    brew = fake_bin / "brew"
    brew.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >>"{calls}"\nexit 0\n', encoding="utf-8"
    )
    brew.chmod(0o755)

    result = subprocess.run(
        ["bash", "scripts/bootstrap.sh", "--platform", "macos",
         "--profile", "desktop", "--gui", "--plan"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "HOME": str(home), "PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-3000:]
    invocations = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    assert invocations == [], f"the plan invoked Homebrew: {invocations[:5]}"
    created = sorted(str(path.relative_to(home)) for path in home.rglob("*"))
    assert created == [], f"plan mutated the home directory: {created}"
