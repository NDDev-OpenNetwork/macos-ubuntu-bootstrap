"""Ubuntu desktop customization reports a real aggregate result offline."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "scripts/ubuntu/desktop.sh"
INSTALL = ROOT / "scripts/ubuntu/install.sh"

# Preconditions desktop.sh checks before it does anything. Each stub is the
# smallest program that satisfies the check without touching the real system.
BASE_STUBS: dict[str, str] = {
    "gsettings": '[ "$1" = "list-schemas" ] && '
                 "echo org.gnome.shell.extensions.dash-to-dock\nexit 0\n",
    "localectl": "exit 0\n",
    "sudo": 'while [ "${1:0:1}" = "-" ]; do shift; done\n[ "$#" -eq 0 ] && exit 0\nexec "$@"\n',
    "locale": "echo ru_RU.utf8\n",
    "sed": "exit 0\n",
    "locale-gen": "exit 0\n",
    "dpkg-query": 'printf "install ok installed"\n',
    "dpkg": "exit 1\n",
    # `snap list firefox >/dev/null 2>&1` discards both streams, so the only
    # way a stub can prove it ran is a side effect on disk.
    "snap": 'touch "$(dirname "$0")/snap-ran"\nexit 1\n',
    "apt-get": "exit 0\n",
    "curl": "exit 0\n",
}


# The package must be reported as absent so the step proceeds past its
# already-installed short circuit, and the download must fail so the test never
# fetches the real artifact.
# `dpkg --print-architecture` must answer here or the .deb step reports
# `skipped` and the test loses its subject. The Chrome step then also attempts
# and fails on a host without Chrome; later independent steps must still run.
DEB_STEP_FAILS: dict[str, str] = {
    "dpkg": '[ "$1" = "--print-architecture" ] && { echo amd64; exit 0; }\nexit 1\n',
    "dpkg-query": "exit 1\n",
    "curl": "exit 1\n",
}


def write_stubs(bin_dir: Path, overrides: dict[str, str] | None = None) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    stubs = {**BASE_STUBS, **(overrides or {})}
    for name, body in stubs.items():
        stub = bin_dir / name
        stub.write_text(f"#!/usr/bin/env bash\n{body}", encoding="utf-8")
        stub.chmod(0o755)
    return bin_dir


def run_desktop(bin_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(DESKTOP)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "RLDYOUR_DRY_RUN": "0",
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        },
    )


def test_all_required_steps_ok_reports_complete(tmp_path: Path) -> None:
    result = run_desktop(write_stubs(tmp_path / "bin"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "desktop customization complete" in result.stdout


def test_failed_deb_step_does_not_skip_the_firefox_step(tmp_path: Path) -> None:
    """The ``die``-inside-``||`` regression: later steps must still run."""
    stubs = write_stubs(tmp_path / "bin", DEB_STEP_FAILS)
    result = run_desktop(stubs)
    combined = result.stdout + result.stderr
    assert (stubs / "snap-ran").exists(), "Firefox removal never ran after the .deb step failed"
    assert "rustdesk: FAILED (required)" in combined
    # google_chrome is required and also fails under these stubs.
    assert result.returncode != 0


def test_required_failure_is_not_reported_as_complete(tmp_path: Path) -> None:
    stubs = write_stubs(tmp_path / "bin", DEB_STEP_FAILS)
    result = run_desktop(stubs)
    combined = result.stdout + result.stderr
    assert "desktop customization incomplete" in combined
    assert "✓ desktop customization complete" not in combined


def test_optional_step_failure_does_not_fail_the_layer(tmp_path: Path) -> None:
    """A cosmetic step must be visible in the report but must not fail apply."""
    stubs = write_stubs(tmp_path / "bin", {"locale": "echo en_US.utf8\n"})
    result = run_desktop(stubs)
    combined = result.stdout + result.stderr
    assert result.returncode == 0
    assert "russian_layout: skipped (precondition absent)" in combined


def test_absent_precondition_is_skipped_not_failed(tmp_path: Path) -> None:
    stubs = write_stubs(tmp_path / "bin", {"gsettings": "exit 0\n"})
    result = run_desktop(stubs)
    combined = result.stdout + result.stderr
    assert result.returncode == 0
    assert "gnome_dock: skipped" in combined


# ----------------------------- wiring -----------------------------


def test_no_step_terminates_the_script_instead_of_returning() -> None:
    """``die`` is ``exit``; a step that calls it cannot be made independent."""
    source = DESKTOP.read_text(encoding="utf-8")
    body = source.split("# ----------------------------- GNOME dock", 1)[1]
    offenders = [
        line.strip()
        for line in body.splitlines()
        if "die " in line and not line.strip().startswith("#")
    ]
    assert offenders == [], f"steps must return, not exit: {offenders}"


def test_installer_surfaces_the_desktop_result_instead_of_warning() -> None:
    source = INSTALL.read_text(encoding="utf-8")
    assert "GUI_LAYER_FAILED=1" in source
    assert 'desktop customization reported issues (non-fatal)' not in source
    # The failure is reported at the end of main, so a required GUI failure
    # cannot strand the layers that run after it.
    main = source.split("main() {", 1)[1]
    assert main.index("install_gui_apps") < main.index('if [ "$GUI_LAYER_FAILED" -ne 0 ]')


def test_every_owned_shell_script_is_linted() -> None:
    """lint.sh discovers scripts instead of carrying a hand-maintained list."""
    lint = (ROOT / "scripts/ci/lint.sh").read_text(encoding="utf-8")
    # What must not come back is a hand-maintained list of paths, not the name
    # of the array that discovery fills.
    assert "$REPO_ROOT/scripts/" not in lint, "lint.sh hardcodes a script path"
    assert "find" in lint and "-name '*.sh'" in lint
    discovered = sorted(p.relative_to(ROOT) for p in (ROOT / "scripts").rglob("*.sh"))
    for required in (
        Path("scripts/ubuntu/desktop.sh"),
        Path("scripts/remote-exec.sh"),
    ):
        assert required in discovered


@pytest.mark.parametrize(
    "script",
    sorted(str(p.relative_to(ROOT)) for p in (ROOT / "scripts").rglob("*.sh")),
)
def test_discovered_script_passes_syntax_check(script: str) -> None:
    result = subprocess.run(
        ["bash", "-n", str(ROOT / script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


# ----------------------------- Google Chrome -----------------------------
#
# Chrome is the one desktop app deliberately not pinned to a SHA-256: pinning a
# browser to an old build is a security liability. Supply-chain control comes
# from the signing key, so the fingerprint gate is the thing worth testing.

CHROME_FINGERPRINT = "EB4C1BFD4F042F6DDDCCEC917721F63BD38B4796"
CONTRACT = ROOT / "config/rldyour-contract.json"


def _chrome_contract() -> dict:
    import json

    apps = json.loads(CONTRACT.read_text(encoding="utf-8"))["ubuntu_apt_packages"][
        "desktop_apps"
    ]
    for entry in apps:
        if isinstance(entry, dict) and entry.get("name") == "google-chrome-stable":
            return entry
    raise AssertionError("google-chrome-stable is not declared in desktop_apps")


def test_contract_declares_chrome_as_key_verified_not_version_pinned() -> None:
    chrome = _chrome_contract()
    assert chrome["version_policy"] == "tracks-stable-channel"
    source = chrome["apt_source"]
    assert source["key_fingerprint"] == CHROME_FINGERPRINT
    assert source["key_url"].startswith("https://dl.google.com/")
    assert source["vendor_repo_add_once"] == "false"
    assert source["vendor_source_policy"] == "preserve-when-key-verifies"


def test_installer_pins_the_same_fingerprint_as_the_contract() -> None:
    source = DESKTOP.read_text(encoding="utf-8")
    assert f'CHROME_KEY_FINGERPRINT="{CHROME_FINGERPRINT}"' in source
    verify = (ROOT / "scripts/ubuntu/verify.sh").read_text(encoding="utf-8")
    assert CHROME_FINGERPRINT in verify, "the verifier must gate on the same key"


def test_chrome_and_rustdesk_are_required() -> None:
    source = DESKTOP.read_text(encoding="utf-8")
    assert "REQUIRED_STEPS=(google_chrome rustdesk firefox_removal)" in source
    body = source.split("nddev::desktop_configure() {", 1)[1]
    assert "nddev::_step rustdesk nddev::_install_desktop_deb rustdesk" in body
    assert "OPTIONAL_STEPS=(gnome_dock russian_layout)" in source


def _extract(function: str, path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out, inside = [], False
    for line in lines:
        if line.startswith(f"{function}()"):
            inside = True
        if inside:
            out.append(line)
            if line.rstrip() == "}":
                break
    assert out, f"{function} not found in {path}"
    return "".join(out)


def test_chrome_key_gate_rejects_a_foreign_key(tmp_path: Path) -> None:
    """A key that is not Google's must never satisfy the gate."""
    gnupg = tmp_path / "gnupg"
    gnupg.mkdir(mode=0o700)
    batch = tmp_path / "batch"
    batch.write_text(
        "%no-protection\nKey-Type: eddsa\nKey-Curve: ed25519\n"
        "Name-Real: Not Google\nName-Email: nobody@example.invalid\n%commit\n",
        encoding="utf-8",
    )
    generated = subprocess.run(
        ["gpg", "--batch", "--homedir", str(gnupg), "--gen-key", str(batch)],
        capture_output=True, text=True, check=False,
    )
    if generated.returncode != 0:
        pytest.skip(f"gpg could not generate a test key: {generated.stderr[:200]}")
    foreign = tmp_path / "foreign.asc"
    exported = subprocess.run(
        ["gpg", "--batch", "--homedir", str(gnupg), "--armor", "--export"],
        capture_output=True, check=False,
    )
    foreign.write_bytes(exported.stdout)

    gate = _extract("nddev::_chrome_keyring_verifies", DESKTOP)
    result = subprocess.run(
        ["bash", "-c",
         f'CHROME_KEY_FINGERPRINT="{CHROME_FINGERPRINT}"\n{gate}\n'
         f'nddev::_chrome_keyring_verifies "$1"', "_", str(foreign)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0, "a foreign signing key was accepted"


def test_chrome_key_gate_rejects_a_missing_keyring(tmp_path: Path) -> None:
    gate = _extract("nddev::_chrome_keyring_verifies", DESKTOP)
    result = subprocess.run(
        ["bash", "-c",
         f'CHROME_KEY_FINGERPRINT="{CHROME_FINGERPRINT}"\n{gate}\n'
         f'nddev::_chrome_keyring_verifies "$1"', "_", str(tmp_path / "absent.asc")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0


def test_verifier_survives_a_device_without_any_chrome_source() -> None:
    """grep exits 1 when it finds nothing; under `set -o pipefail` an unguarded
    command substitution would abort the whole verifier on such a device."""
    verify = (ROOT / "scripts/ubuntu/verify.sh").read_text(encoding="utf-8")
    block = verify.split("chrome_source=", 1)[1].split("\n\n", 1)[0]
    assert "|| true" in block, "the Chrome source lookup must not abort under pipefail"


def test_both_google_repository_paths_are_recognised() -> None:
    """Google's cron writes linux/chrome/deb; repolib writes
    linux/chrome-stable/deb. Matching only the former left a real device's
    source invisible to both the installer and the verifier."""
    for path in (DESKTOP, ROOT / "scripts/ubuntu/verify.sh"):
        text = path.read_text(encoding="utf-8")
        assert "dl.google.com/linux/chrome" in text, path.name
        assert "dl.google.com/linux/chrome/deb'" not in text, (
            f"{path.name} still matches only the cron path"
        )


# ------------------- pinned .deb applications (one installer) -------------------


def _deb_rows() -> list[list[str]]:
    source = DESKTOP.read_text(encoding="utf-8")
    block = re.search(r"^DESKTOP_DEBS=\((.*?)^\)", source, re.M | re.S)
    assert block, "DESKTOP_DEBS table missing"
    return [
        line.strip().strip('"').split(";")
        for line in block.group(1).splitlines()
        if line.strip().startswith('"')
    ]


def test_every_deb_application_goes_through_one_installer() -> None:
    source = DESKTOP.read_text(encoding="utf-8")
    assert source.count("nddev::_install_desktop_deb()") == 1
    assert {row[0] for row in _deb_rows()} == {"rustdesk"}


def test_every_deb_row_is_well_formed_and_digest_pinned() -> None:
    for row in _deb_rows():
        assert len(row) == 6, f"malformed row: {row}"
        name, package, url_x64, sha_x64, url_arm64, sha_arm64 = row
        assert name and package
        assert url_x64.startswith("https://")
        assert re.fullmatch(r"[0-9a-f]{64}", sha_x64), f"{name}: bad x64 digest"
        # An arm64 build is optional, but a URL without a digest is never valid.
        assert bool(url_arm64) == bool(sha_arm64), f"{name}: half-declared arm64"
        if url_arm64:
            assert url_arm64.startswith("https://")
            assert re.fullmatch(r"[0-9a-f]{64}", sha_arm64), f"{name}: bad arm64 digest"


def test_deb_rows_match_the_contract() -> None:
    """One shape for one concept: every declared .deb is per-architecture."""
    import json

    apps = json.loads(CONTRACT.read_text(encoding="utf-8"))["ubuntu_apt_packages"][
        "desktop_apps"
    ]
    declared = {
        entry["name"]: entry
        for entry in apps
        if isinstance(entry, dict) and "sha256" in entry
    }
    rows = {row[0]: row for row in _deb_rows()}
    assert set(rows) == set(declared), "installer table and contract disagree"

    for name, row in rows.items():
        _name, _package, url_x64, sha_x64, url_arm64, sha_arm64 = row
        spec = declared[name]
        assert isinstance(spec["sha256"], dict), f"{name}: flat digest, expected per-arch"
        assert spec["sha256"]["x64"] == sha_x64, name
        assert spec["url"]["x64"] == url_x64, name
        # An architecture upstream does not publish must be absent from both
        # sides, never half-declared.
        assert ("arm64" in spec["sha256"]) == bool(sha_arm64), name
        if sha_arm64:
            assert spec["sha256"]["arm64"] == sha_arm64, name
            assert spec["url"]["arm64"] == url_arm64, name


def test_unknown_deb_row_is_refused(tmp_path: Path) -> None:
    source = DESKTOP.read_text(encoding="utf-8")
    table_match = re.search(r"^DESKTOP_DEBS=\(.*?^\)", source, re.M | re.S)
    assert table_match, "DESKTOP_DEBS table missing"
    table = table_match.group(0)
    fn = _extract("nddev::_install_desktop_deb", DESKTOP)
    result = subprocess.run(
        ["bash", "-c",
         "info(){ :; }; ok(){ :; }; warn(){ printf '%s\\n' \"$*\"; }\n"
         "nddev::_record(){ :; }; nddev::_sudo_refresh(){ :; }\n"
         f"{table}\n{fn}\nnddev::_install_desktop_deb nonesuch"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "no DESKTOP_DEBS row named nonesuch" in result.stdout


# ------------------- macOS: an optional layer cannot strand the rest -------------------
#
# macos/install.sh runs the GUI cask layer BEFORE the mandatory browser layer.
# The loop used to call ensure_cask bare under `set -euo pipefail`, so one
# unavailable cask aborted the script and took the language servers, the
# mandatory browser layer, the harness layer and verification with it. This is
# the failure this repository already fixed twice on the Ubuntu side.

MACOS_INSTALL = ROOT / "scripts/macos/install.sh"


def test_macos_gui_layer_attempts_every_cask() -> None:
    source = MACOS_INSTALL.read_text(encoding="utf-8")
    body = source.split("install_gui_apps() {", 1)[1].split("\n}", 1)[0]
    assert "if ! ensure_cask" in body, (
        "a bare ensure_cask under set -e aborts the whole run on the first "
        "failing cask"
    )
    assert "GUI_LAYER_FAILED" in body


def test_macos_gui_failure_is_reported_after_all_install_layers() -> None:
    source = MACOS_INSTALL.read_text(encoding="utf-8")
    main = source.split("main() {", 1)[1]
    gui = main.index("install_gui_apps")
    harnesses = main.index("install_ai_runtimes")
    report = main.index('if [ "$GUI_LAYER_FAILED" -ne 0 ]')
    assert gui < harnesses, "unexpected ordering; re-derive this test"
    assert harnesses < report, (
        "the GUI result must be reported after the mandatory layers have run, "
        "not before them"
    )


def test_macos_gui_failure_still_fails_the_run() -> None:
    """Attempting everything must not become reporting success."""
    source = MACOS_INSTALL.read_text(encoding="utf-8")
    main = source.split("main() {", 1)[1]
    report = main.index('if [ "$GUI_LAYER_FAILED" -ne 0 ]')
    assert "return 1" in main[report : report + 300]


# ------------------- the minimum-version gate must actually gate -------------------
#
# rldyour::require_cmd_min_version is used only by macos/verify.sh, for node,
# uv, bun, starship, atuin, carapace and dart. It returned 0 -- "skipping
# numeric check" -- whenever it could not parse a version, and it discarded
# stderr while doing so. The Ubuntu code documents that `dart --version` printed
# to stderr on older SDKs and reads both streams for that reason, so the macOS
# gate could pass Dart without ever comparing its version.

COMMON = ROOT / "scripts/lib/common.sh"


def _min_version(tool: Path, minimum: str = "1.0") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c",
         f'source "{COMMON}"\nrldyour::require_cmd_min_version {tool.name} {minimum} --version'],
        capture_output=True, text=True, check=False,
        env={**os.environ, "PATH": f"{tool.parent}{os.pathsep}{os.environ['PATH']}"},
    )


def _tool(tmp_path: Path, name: str, body: str) -> Path:
    tool = tmp_path / name
    tool.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    tool.chmod(0o755)
    return tool


def test_min_version_accepts_a_current_version(tmp_path: Path) -> None:
    assert _min_version(_tool(tmp_path, "good", 'echo "1.2.3"\n')).returncode == 0


def test_min_version_rejects_an_old_version(tmp_path: Path) -> None:
    assert _min_version(_tool(tmp_path, "old", 'echo "0.9.0"\n')).returncode != 0


def test_min_version_reads_a_version_reported_on_stderr(tmp_path: Path) -> None:
    """The exact shape of `dart --version` on older SDKs."""
    tool = _tool(tmp_path, "stderrtool", 'echo "Dart SDK version: 3.12.2" >&2\n')
    result = _min_version(tool)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3.12.2" in result.stdout


def test_min_version_fails_closed_when_no_version_can_be_read(tmp_path: Path) -> None:
    """It used to return 0 here, so a broken binary satisfied the gate."""
    result = _min_version(_tool(tmp_path, "silent", "exit 0\n"))
    assert result.returncode != 0, "an unreadable version must not pass a version gate"
    assert "could not detect version" in result.stdout
    assert "skipping numeric check" not in result.stdout


# ------------------- bash 3.2 portability on the macOS path -------------------
#
# macOS still ships bash 3.2. The repository's own lint script used `mapfile`
# and died with "command not found" on the macOS CI lane -- in an adapter whose
# whole purpose is to support both platforms. The lane caught it; nothing local
# did.

# bash 4.0+ only. Each would be a runtime failure on macOS, not a syntax error,
# so `bash -n` does not see them.
BASH4_ONLY = (
    (r"\bmapfile\b", "mapfile is bash 4.0+"),
    (r"\breadarray\b", "readarray is bash 4.0+"),
    (r"declare\s+-A\b", "associative arrays are bash 4.0+"),
    (r"\$\{[A-Za-z_][A-Za-z0-9_]*\^\^", "${var^^} is bash 4.0+"),
    (r"\$\{[A-Za-z_][A-Za-z0-9_]*,,", "${var,,} is bash 4.0+"),
)

# Scripts that execute on macOS: the compositor, the shared library, the macOS
# platform scripts and every repository-level entry point. The ubuntu/ scripts
# are Linux-only and may use bash 4 freely.
MACOS_PATH_SCRIPTS = [
    "scripts/ci/lint.sh",
    "scripts/ci/validate.sh",
    "scripts/bootstrap.sh",
    "scripts/lib/common.sh",
    "scripts/macos/install.sh",
    "scripts/macos/verify.sh",
    "scripts/auth-handoff.sh",
    "scripts/remote-exec.sh",
]


@pytest.mark.parametrize("script", MACOS_PATH_SCRIPTS)
def test_macos_path_scripts_avoid_bash4_only_features(script: str) -> None:
    path = ROOT / script
    assert path.exists(), f"{script} is listed here but does not exist"
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        for pattern, why in BASH4_ONLY:
            assert not re.search(pattern, line), (
                f"{script}:{number} uses a construct macOS bash 3.2 lacks — {why}\n"
                f"  {line.strip()}"
            )


def test_the_macos_path_list_covers_every_non_ubuntu_script() -> None:
    """A new top-level script must be classified, not silently unchecked."""
    owned = {
        str(p.relative_to(ROOT))
        for p in (ROOT / "scripts").rglob("*.sh")
        if "ubuntu" not in p.parts
    }
    assert owned == set(MACOS_PATH_SCRIPTS), (
        f"unclassified scripts: {sorted(owned ^ set(MACOS_PATH_SCRIPTS))}"
    )
