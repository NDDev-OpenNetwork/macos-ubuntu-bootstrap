"""Contract parity tests: the contract JSON must match the installer code.

Extends the pattern established by test_compiled_language_hosts.py
(test_installer_constants_match_the_contract) to cover the domains that were
previously unchecked: apt baseline, cloak runtime packages, macOS GUI casks,
and Node/uv/Bun version+hash constants. A drift between the contract and the
installer is caught here at CI time, before it can ship to a device.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads((ROOT / "config/rldyour-contract.json").read_text(encoding="utf-8"))
UBUNTU_INSTALL = (ROOT / "scripts/ubuntu/install.sh").read_text(encoding="utf-8")
MACOS_INSTALL = (ROOT / "scripts/macos/install.sh").read_text(encoding="utf-8")


def _parse_bash_array(source: str, name: str) -> set[str]:
    """Extract a bash array (NAME=(...)) into a set[str]."""
    match = re.search(rf"{re.escape(name)}=\(\s*(.*?)\)", source, re.DOTALL)
    assert match is not None, f"{name} array not found"
    return set(re.findall(r"\S+", match.group(1)))


def _constant(source: str, name: str) -> str:
    """Extract a bash scalar constant NAME=\"value\" from source."""
    match = re.search(rf'^{name}="([^"]+)"', source, re.M)
    assert match is not None, f"{name} missing from installer source"
    return match.group(1)


# ----------------------------- apt packages -----------------------------


def test_apt_baseline_matches_contract() -> None:
    """APT_SOURCE_PACKAGES + software-properties-common == contract baseline."""
    code = _parse_bash_array(UBUNTU_INSTALL, "APT_SOURCE_PACKAGES")
    code.add("software-properties-common")  # installed separately at install.sh:257
    contract = set(CONTRACT["ubuntu_apt_packages"]["baseline"])
    assert code == contract, (
        f"apt baseline drift:\n  in code only: {code - contract}\n  in contract only: {contract - code}"
    )


def test_apt_cloak_runtime_matches_contract() -> None:
    """APT_CLOAK_RUNTIME_PACKAGES == contract cloak_runtime."""
    code = _parse_bash_array(UBUNTU_INSTALL, "APT_CLOAK_RUNTIME_PACKAGES")
    contract = set(CONTRACT["ubuntu_apt_packages"]["cloak_runtime"])
    assert code == contract, (
        f"cloak runtime drift:\n  in code only: {code - contract}\n  in contract only: {contract - code}"
    )


def test_apt_profiles_reference_valid_groups() -> None:
    """Every profile must reference only groups that exist in the contract."""
    groups = {k for k in CONTRACT["ubuntu_apt_packages"] if not k.startswith("_") and k != "profiles"}
    for profile, refs in CONTRACT["ubuntu_apt_packages"]["profiles"].items():
        for ref in refs:
            assert ref in groups, f"profile {profile} references unknown group {ref}"


# ----------------------------- macOS GUI casks -----------------------------


def test_gui_casks_match_contract() -> None:
    """macOS GUI_CASKS array == contract gui.macos list."""
    code = _parse_bash_array(MACOS_INSTALL, "GUI_CASKS")
    contract = set(CONTRACT["gui"]["macos"])
    assert code == contract, (
        f"GUI casks drift:\n  in code only: {code - contract}\n  in contract only: {contract - code}"
    )


# ----------------------------- Node / uv / Bun constants -----------------------------


def test_node_constants_match_contract() -> None:
    """Node version + SHA-256 in install.sh == contract runtime_support."""
    runtime = CONTRACT["runtime_support"]
    assert _constant(UBUNTU_INSTALL, "NODE_VERSION") == runtime["ubuntu_node_lts"]
    assert _constant(UBUNTU_INSTALL, "NODE_SHA256_X64") == runtime["ubuntu_node_sha256"]["x64"]
    assert _constant(UBUNTU_INSTALL, "NODE_SHA256_ARM64") == runtime["ubuntu_node_sha256"]["arm64"]


def test_uv_constants_match_contract() -> None:
    """uv version + SHA-256 in install.sh == contract runtime_support."""
    runtime = CONTRACT["runtime_support"]
    assert _constant(UBUNTU_INSTALL, "UV_VERSION") == runtime["ubuntu_uv"]
    assert _constant(UBUNTU_INSTALL, "UV_SHA256_X64") == runtime["ubuntu_uv_sha256"]["x64"]
    assert _constant(UBUNTU_INSTALL, "UV_SHA256_ARM64") == runtime["ubuntu_uv_sha256"]["arm64"]


def test_bun_constants_match_contract() -> None:
    """Bun version + SHA-256 in install.sh == contract runtime_support."""
    runtime = CONTRACT["runtime_support"]
    assert _constant(UBUNTU_INSTALL, "BUN_VERSION") == runtime["ubuntu_bun"]
    assert _constant(UBUNTU_INSTALL, "BUN_SHA256_X64") == runtime["ubuntu_bun_sha256"]["x64"]
    assert _constant(UBUNTU_INSTALL, "BUN_SHA256_ARM64") == runtime["ubuntu_bun_sha256"]["arm64"]


# ----------------------------- USER_TOOLS (herdr) -----------------------------


def _parse_user_tool_rows(source: str) -> dict[str, list[str]]:
    """Parse the USER_TOOLS bash array into {name: [fields]}.

    Each row is ``name;version;kind;member_x64;member_arm64;link;
    sha_x64;sha_arm64;url_x64;url_arm64`` — the same contract as
    PINNED_SOURCE_TOOLS.
    """
    match = re.search(r"USER_TOOLS=\(\s*(.*?)\n\)", source, re.DOTALL)
    assert match is not None, "USER_TOOLS array not found"
    rows: dict[str, list[str]] = {}
    for raw in re.findall(r'"([^"]+)"', match.group(1)):
        fields = raw.split(";")
        rows[fields[0]] = fields
    return rows


def test_user_tools_match_the_contract() -> None:
    """USER_TOOLS bash array must match contract user_tools: name, version, SHA-256."""
    declared = CONTRACT.get("user_tools", {})
    rows = _parse_user_tool_rows(UBUNTU_INSTALL)
    assert set(declared) == set(rows), (
        f"contract and installer disagree on user_tools set:\n"
        f"  contract only: {set(declared) - set(rows)}\n"
        f"  installer only: {set(rows) - set(declared)}"
    )
    for name, row in rows.items():
        spec = declared[name]
        assert row[1] == spec["version"], f"{name}: version drift ({row[1]} vs {spec['version']})"
        # herdr uses per-arch sha256 dict; telegram uses a single archive_sha256
        # (same hash for both arch slots in the bash array since the tarball is
        # x86_64-only and the arm64 slot is a mirror for the parser).
        if "sha256" in spec:
            assert row[6] == spec["sha256"]["x86_64"], f"{name}: x64 SHA-256 drift"
            assert row[7] == spec["sha256"]["aarch64"], f"{name}: arm64 SHA-256 drift"
        elif "archive_sha256" in spec:
            assert row[6] == spec["archive_sha256"], f"{name}: archive SHA-256 drift"
            assert row[7] == spec["archive_sha256"], f"{name}: archive SHA-256 (arm64 slot) drift"


def test_browseros_deb_url_and_sha_in_contract() -> None:
    """BrowserOS .deb must be versioned (not CDN latest) with a pinned SHA-256."""
    desktop_apps = CONTRACT["ubuntu_apt_packages"]["desktop_apps"]
    browseros = next(app for app in desktop_apps if isinstance(app, dict) and app.get("name") == "browseros")
    assert "version" in browseros, "browseros desktop_app missing version"
    assert "sha256" in browseros, "browseros desktop_app missing sha256"
    assert "github.com" in browseros["url"], (
        f"browseros URL must be a versioned GitHub release, not CDN latest: {browseros['url']}"
    )
    assert browseros["sha256"] != "", "browseros sha256 must not be empty"


def test_browseros_desktop_sh_uses_versioned_url_and_sha() -> None:
    """desktop.sh must download BrowserOS from the versioned GitHub URL with SHA-256 verification."""
    desktop_sh = (ROOT / "scripts/ubuntu/desktop.sh").read_text(encoding="utf-8")
    browseros = next(
        app for app in CONTRACT["ubuntu_apt_packages"]["desktop_apps"]
        if isinstance(app, dict) and app.get("name") == "browseros"
    )
    assert browseros["url"] in desktop_sh, (
        f"desktop.sh missing versioned BrowserOS URL: {browseros['url']}"
    )
    assert browseros["sha256"] in desktop_sh, (
        "desktop.sh missing BrowserOS SHA-256 constant"
    )
    assert "download_verified_file" in desktop_sh, (
        "desktop.sh must use rldyour::download_verified_file, not bare wget"
    )
    assert "cdn.browseros.com" not in desktop_sh, (
        "desktop.sh must not reference the volatile CDN latest pointer"
    )


