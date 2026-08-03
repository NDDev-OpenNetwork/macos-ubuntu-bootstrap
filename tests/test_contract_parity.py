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
