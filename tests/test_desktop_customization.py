"""Ubuntu desktop customization reports a real aggregate result.

The composer used to run four ``step || warn`` lines and then print
"desktop customization complete" unconditionally, so a desktop missing
BrowserOS or still carrying Firefox passed both apply and strict verification.
Worse, one of those four steps did not warn at all: it called ``die``, which is
``exit 1``, and ``exit`` inside a function on the left of ``||`` terminates the
whole script -- so a failed BrowserOS install skipped the Firefox removal that
was supposed to be independent of it.

Every stub here is deliberately offline. The BrowserOS failure path reports the
package as absent and then fails ``curl``, so the suite never fetches the real
216 MB artifact.
"""

from __future__ import annotations

import os
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


# BrowserOS must be reported as absent so the step proceeds past its
# already-installed short circuit, and the download must fail so the test never
# fetches the real package.
BROWSEROS_FAILS: dict[str, str] = {"dpkg-query": "exit 1\n", "curl": "exit 1\n"}


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


def test_failed_browseros_does_not_skip_the_firefox_step(tmp_path: Path) -> None:
    """The ``die``-inside-``||`` regression: later steps must still run."""
    stubs = write_stubs(tmp_path / "bin", BROWSEROS_FAILS)
    result = run_desktop(stubs)
    combined = result.stdout + result.stderr
    assert (stubs / "snap-ran").exists(), "Firefox removal never ran after BrowserOS failed"
    assert "browseros: FAILED (required)" in combined
    assert result.returncode != 0


def test_required_failure_is_not_reported_as_complete(tmp_path: Path) -> None:
    stubs = write_stubs(tmp_path / "bin", BROWSEROS_FAILS)
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
    assert "russian_layout: failed (optional)" in combined
    assert "optional step(s) failed" in combined


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
    assert "SCRIPT_PATHS=(" not in lint.replace("SCRIPT_PATHS=(\"${filtered[@]}\")", "")
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


def test_chrome_is_a_required_desktop_step() -> None:
    source = DESKTOP.read_text(encoding="utf-8")
    assert "REQUIRED_STEPS=(browseros google_chrome firefox_removal)" in source
    body = source.split("nddev::desktop_configure() {", 1)[1]
    assert body.index("nddev::_step browseros") < body.index("nddev::_step google_chrome")


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
        assert "'dl.google.com/linux/chrome'" in text, path.name
        assert "dl.google.com/linux/chrome/deb'" not in text, (
            f"{path.name} still matches only the cron path"
        )
