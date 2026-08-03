"""Profile dispatch isolation tests.

These tests verify that the three bootstrap profiles (macOS desktop, Ubuntu
desktop+gui, Ubuntu desktop+no-gui, Ubuntu server) are genuinely isolated:
server-only code (Docker, openssh, UFW, hardening) cannot execute in a desktop
bootstrap, and desktop-only code (compilers, GUI customization, .desktop
launchers) cannot execute in a server bootstrap.

Three layers of testing, each progressively stronger:

1. Plan-mode dispatch (B1) — run bootstrap.sh in plan mode with each profile
   and assert which section headers and skip-messages appear/don't appear in
   stdout. This exercises the full composition: bootstrap.sh arg parsing →
   env export → install.sh guard → section logging.

2. Exit-2 validation coverage (B2) — every bootstrap.sh argument-validation
   rule is exercised with an invalid combination, asserting both exit code and
   the specific stderr message.

3. validate_target unit tests (B3) — source install.sh (now safe after the
   BASH_SOURCE guard) and call validate_target directly with controlled env,
   asserting that the composition-matrix allowlist accepts/rejects tuples.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts/bootstrap.sh"
INSTALL = ROOT / "scripts/ubuntu/install.sh"
COMMON = ROOT / "scripts/lib/common.sh"


# ----------------------------- helpers -----------------------------


def run_plan(*args: str) -> str:
    """Run bootstrap.sh in plan mode and return stdout+stderr."""
    result = subprocess.run(
        ["bash", str(BOOTSTRAP), *args, "--skip-ai"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        env={**os.environ, "RLDYOUR_DRY_RUN": "1"},
    )
    return result.stdout + result.stderr


def run_plan_full(*args: str) -> str:
    """Run bootstrap.sh in plan mode with ALL skip flags for speed."""
    result = subprocess.run(
        [
            "bash", str(BOOTSTRAP), *args,
            "--plan", "--skip-system", "--skip-ai", "--skip-lsps", "--skip-checks",
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        env={**os.environ},
    )
    return result.stdout + result.stderr


def run_invalid(*args: str) -> subprocess.CompletedProcess[str]:
    """Run bootstrap.sh with an invalid argument combination."""
    return subprocess.run(
        ["bash", str(BOOTSTRAP), *args, "--plan"],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


def source_install(body: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Source install.sh (safe after BASH_SOURCE guard) and run body in the same shell."""
    merged = {**os.environ, **(env or {})}
    merged.setdefault("RLDYOUR_DRY_RUN", "1")
    return subprocess.run(
        ["bash", "-c", f'source "$1"\n{body}', "_", str(INSTALL)],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        env=merged,
    )


# ----------------------------- B1: plan-mode dispatch -----------------------------


def test_server_does_not_plan_gui_or_desktop_customization() -> None:
    """Server profile must never plan GUI apps or GNOME desktop customization."""
    output = run_plan_full("--platform", "ubuntu", "--profile", "server", "--docker-mode", "rootful")
    assert "GUI application layer disabled" in output
    assert "Install verified Ubuntu GUI applications" not in output
    assert "Configure Ubuntu desktop" not in output
    assert "desktop.sh" not in output


def test_server_does_not_plan_user_tools_or_desktop_entries() -> None:
    """Server profile must not install herdr or .desktop launchers."""
    output = run_plan_full("--platform", "ubuntu", "--profile", "server", "--docker-mode", "rootful")
    # The desktop-only block (install_user_tools + install_desktop_entries) is
    # gated by PROFILE=desktop. Server must not reach it.
    assert "managed herdr" not in output
    assert "herdr.desktop" not in output


def test_desktop_does_not_plan_server_layer() -> None:
    """Desktop profile must never plan Docker, openssh-server, UFW, or hardening."""
    output = run_plan_full("--platform", "ubuntu", "--profile", "desktop", "--gui")
    # Server-layer specific strings that must not appear in a desktop plan.
    assert "docker-ce" not in output
    assert "openssh-server" not in output
    assert "unattended-upgrades" not in output
    # The server layer section header (from run_server_layer) must not appear.
    # run_server_layer is a silent return-0 for desktop, but if the guard were
    # removed, the server.sh invocation would show in plan output.
    assert "Ubuntu server layer" not in output


def test_desktop_no_gui_skips_desktop_customization_but_keeps_toolchain() -> None:
    """Desktop+no-gui: skips GNOME/.desktop but retains terminal/LSP/browser stack."""
    output = run_plan_full("--platform", "ubuntu", "--profile", "desktop", "--no-gui")
    assert "GUI application layer disabled" in output
    assert "desktop entries skipped: gui disabled" in output
    assert "Configure Ubuntu desktop" not in output
    assert "desktop.sh" not in output
    # Browser layer is mandatory regardless of GUI mode.
    assert "CloakBrowser" in output


def test_desktop_gui_includes_desktop_customization() -> None:
    """Desktop+gui: includes GNOME customization and .desktop entries."""
    output = run_plan_full("--platform", "ubuntu", "--profile", "desktop", "--gui")
    assert "Install verified Ubuntu GUI applications" in output
    assert "Configure Ubuntu desktop" in output


def test_server_plans_compiled_hosts_skip_message() -> None:
    """Server profile must emit the compiled-language-hosts skip message."""
    output = run_plan("--platform", "ubuntu", "--profile", "server")
    assert "compiled-language LSP hosts skipped" in output


def test_browser_is_mandatory_on_all_profiles() -> None:
    """CloakBrowser must appear in plan output for every profile/mode."""
    combos = [
        ("--platform", "ubuntu", "--profile", "desktop", "--gui"),
        ("--platform", "ubuntu", "--profile", "desktop", "--no-gui"),
        ("--platform", "ubuntu", "--profile", "server", "--docker-mode", "rootful"),
        ("--platform", "ubuntu", "--profile", "server", "--docker-mode", "rootless"),
    ]
    for combo in combos:
        output = run_plan_full(*combo)
        assert "CloakBrowser" in output, f"browser missing from plan: {combo}"


# ----------------------------- B2: exit-2 validation coverage -----------------------------


# Each case: (args, expected_stderr_substring).
# These are the rules NOT covered by the existing test_invalid_profile_combinations_fail_closed.
INVALID_COMBOS: list[tuple[tuple[str, ...], str]] = [
    (("--platform", "foo"), "Unsupported platform: foo"),
    (("--platform", "ubuntu", "--profile", "foo"), "Unsupported profile: foo"),
    (("--platform", "ubuntu", "--profile", "desktop", "--docker-mode", "foo"), "Unsupported Docker mode: foo"),
    (("--platform", "macos", "--profile", "desktop", "--docker-mode", "rootful"), "cannot install Docker"),
    (("--platform", "ubuntu", "--profile", "desktop", "--docker-mode", "rootless"), "cannot install Docker"),
    (("--platform", "ubuntu", "--profile", "desktop", "--harden-ssh"), "Server hardening flags require"),
    (("--platform", "ubuntu", "--profile", "desktop", "--enable-ufw"), "Server hardening flags require"),
    (("--platform", "ubuntu", "--profile", "desktop", "--with-fail2ban"), "Server hardening flags require"),
]


@pytest.mark.parametrize("args, expected_message", INVALID_COMBOS)
def test_invalid_combination_exits_nonzero_with_message(args: tuple[str, ...], expected_message: str) -> None:
    result = run_invalid(*args)
    assert result.returncode != 0, f"expected non-zero exit for {args}, got 0"
    assert expected_message in result.stderr, (
        f"expected stderr to contain {expected_message!r} for {args}, "
        f"got: {result.stderr.strip()!r}"
    )


# ----------------------------- B3: validate_target unit tests -----------------------------


# Valid composition tuples that validate_target must accept (return 0).
# Tuple: (PROFILE, LOCAL_EXECUTION_POLICY, DOCKER_MODE, GUI_ENABLED)
VALID_TUPLES: list[tuple[str, str, str, str]] = [
    ("desktop", "source-lsp-only", "none", "0"),
    ("desktop", "source-lsp-only", "none", "1"),
    ("server", "container-execution-only", "none", "0"),
    ("server", "container-execution-only", "rootful", "0"),
    ("server", "container-execution-only", "rootless", "0"),
]


# Invalid composition tuples that validate_target must reject (return 2).
INVALID_TUPLES: list[tuple[str, str, str, str]] = [
    # Desktop cannot have Docker
    ("desktop", "source-lsp-only", "rootful", "0"),
    ("desktop", "source-lsp-only", "rootless", "1"),
    # Server cannot have GUI
    ("server", "container-execution-only", "none", "1"),
    ("server", "container-execution-only", "rootful", "1"),
    # Execution policy must match profile
    ("desktop", "container-execution-only", "none", "0"),
    ("server", "source-lsp-only", "none", "0"),
    # Bogus values
    ("laptop", "source-lsp-only", "none", "0"),
    ("desktop", "source-lsp-only", "podman", "0"),
]


def _validate_target_call(profile: str, policy: str, docker: str, gui: str) -> subprocess.CompletedProcess[str]:
    """Call validate_target with the given tuple in dry-run mode.

    install.sh runs under `set -euo pipefail`, so a bare
    `validate_target; echo $?` would abort the process on return 2 before the
    echo runs. We capture the exit code into a variable first, then print it
    after `|| true` neutralizes set -e.
    """
    body = (
        f'PROFILE="{profile}" '
        f'LOCAL_EXECUTION_POLICY="{policy}" '
        f'DOCKER_MODE="{docker}" '
        f'GUI_ENABLED="{gui}" '
        f'REPO_ROOT="{ROOT}" '
        f'_rc=0; validate_target || _rc=$?; echo "EXIT:$_rc"'
    )
    return source_install(body)


@pytest.mark.parametrize("profile,policy,docker,gui", VALID_TUPLES)
def test_validate_target_accepts_valid_composition(
    profile: str, policy: str, docker: str, gui: str
) -> None:
    result = _validate_target_call(profile, policy, docker, gui)
    assert "EXIT:0" in result.stdout, (
        f"expected validate_target to accept "
        f"{profile}:{policy}:{docker}:{gui}, "
        f"got stdout={result.stdout!r} stderr={result.stderr!r}"
    )


@pytest.mark.parametrize("profile,policy,docker,gui", INVALID_TUPLES)
def test_validate_target_rejects_invalid_composition(
    profile: str, policy: str, docker: str, gui: str
) -> None:
    result = _validate_target_call(profile, policy, docker, gui)
    assert "EXIT:2" in result.stdout, (
        f"expected validate_target to reject "
        f"{profile}:{policy}:{docker}:{gui}, "
        f"got stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# ----------------------------- guard presence (belt-and-suspenders) -----------------------------


def test_install_sh_has_bash_source_guard() -> None:
    """install.sh must guard its main flow so it is safe to source."""
    source = INSTALL.read_text(encoding="utf-8")
    assert '"${BASH_SOURCE[0]}" == "$0"' in source, (
        "install.sh missing BASH_SOURCE guard — cannot be safely sourced for testing"
    )


def test_run_server_layer_guards_on_profile() -> None:
    """run_server_layer must early-return when PROFILE != server."""
    source = INSTALL.read_text(encoding="utf-8")
    # Extract the run_server_layer function body.
    start = source.index("run_server_layer()")
    # The guard should be one of the first statements in the function.
    body = source[start : start + 500]
    assert '[ "$PROFILE" = "server" ] || return 0' in body, (
        "run_server_layer missing PROFILE=server guard"
    )


def test_install_gui_apps_guards_on_profile_and_gui() -> None:
    """install_gui_apps must early-return when PROFILE != desktop OR GUI_ENABLED != 1."""
    source = INSTALL.read_text(encoding="utf-8")
    start = source.index("install_gui_apps()")
    body = source[start : start + 300]
    assert '"$PROFILE" != "desktop"' in body, "install_gui_apps missing PROFILE guard"
    assert '"$GUI_ENABLED" -ne 1' in body, "install_gui_apps missing GUI_ENABLED guard"


def test_install_compiled_language_hosts_guards_on_profile() -> None:
    """install_compiled_language_hosts must early-return when PROFILE != desktop."""
    source = INSTALL.read_text(encoding="utf-8")
    start = source.index("install_compiled_language_hosts()")
    body = source[start : start + 300]
    assert '"$PROFILE" != "desktop"' in body, (
        "install_compiled_language_hosts missing PROFILE guard"
    )
