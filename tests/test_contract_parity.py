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
from urllib.parse import urlparse

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


def test_host_build_packages_are_profile_isolated() -> None:
    code = _parse_bash_array(UBUNTU_INSTALL, "APT_DESKTOP_BUILD_PACKAGES")
    assert code == set(CONTRACT["ubuntu_apt_packages"]["desktop_build"])
    profiles = CONTRACT["ubuntu_apt_packages"]["profiles"]
    assert "desktop_build" in profiles["desktop"]
    assert "desktop_build" in profiles["desktop-builds"]
    assert "desktop_build" not in profiles["server"]


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
        # herdr publishes both architectures and uses a per-arch sha256 dict;
        # telegram publishes x86_64 only and uses a single archive_sha256.
        #
        # This assertion used to REQUIRE the arm64 slot to repeat the x86_64
        # digest for a single-architecture tool, which is how an arm64 desktop
        # came to verify the SHA-256 of a binary it cannot execute. An
        # architecture upstream does not publish must be declared absent.
        if "sha256" in spec:
            assert row[6] == spec["sha256"]["x86_64"], f"{name}: x64 SHA-256 drift"
            assert row[7] == spec["sha256"]["aarch64"], f"{name}: arm64 SHA-256 drift"
        elif "archive_sha256" in spec:
            assert row[6] == spec["archive_sha256"], f"{name}: archive SHA-256 drift"
            architectures = spec.get("architectures", ["x86_64", "aarch64"])
            if "aarch64" in architectures:
                assert row[7] == spec["archive_sha256"], f"{name}: arm64 SHA-256 drift"
            else:
                assert row[7] == "", (
                    f"{name}: contract declares {architectures} but the row fills "
                    "the arm64 slot; an unpublished architecture must be empty"
                )
                assert row[9] == "", f"{name}: arm64 URL must be empty too"
        if "archive_kind" in spec:
            assert row[2] == spec["archive_kind"], (
                f"{name}: archive kind drift ({row[2]} vs {spec['archive_kind']})"
            )


def _declared_debs() -> dict:
    """Every desktop_apps entry distributed as a pinned .deb."""
    return {
        app["name"]: app
        for app in CONTRACT["ubuntu_apt_packages"]["desktop_apps"]
        if isinstance(app, dict) and "sha256" in app
    }


def test_every_declared_deb_is_versioned_and_digest_pinned() -> None:
    """Generalised from a BrowserOS-only check: the guard must cover every
    .deb application, or the next one added silently escapes it."""
    debs = _declared_debs()
    assert debs, "no .deb applications declared"
    for name, app in debs.items():
        assert "version" in app, f"{name}: missing version"
        assert isinstance(app["sha256"], dict), f"{name}: digest must be per-architecture"
        assert isinstance(app["url"], dict), f"{name}: url must be per-architecture"
        assert set(app["url"]) == set(app["sha256"]), f"{name}: url/digest arches disagree"
        for arch, url in app["url"].items():
            # Compare the parsed host, never a substring: `github.com` appears
            # in https://github.com.attacker.example/ and in any query string,
            # so a substring test would admit exactly the artifact this guard
            # exists to reject. CodeQL flagged the earlier version as
            # py/incomplete-url-substring-sanitization, correctly.
            parsed = urlparse(url)
            assert parsed.scheme == "https", f"{name}/{arch} is not https: {url}"
            assert parsed.hostname == "github.com", (
                f"{name}/{arch} must be a versioned GitHub release, not {parsed.hostname}: {url}"
            )
            assert "/latest/" not in parsed.path, (
                f"{name}/{arch} uses a volatile latest pointer"
            )
            assert app["version"] in url, (
                f"{name}/{arch} URL does not carry the declared version {app['version']}"
            )
            assert re.fullmatch(r"[0-9a-f]{64}", app["sha256"][arch]), (
                f"{name}/{arch}: malformed digest"
            )


def test_desktop_sh_downloads_every_declared_deb_verified() -> None:
    desktop_sh = (ROOT / "scripts/ubuntu/desktop.sh").read_text(encoding="utf-8")
    for name, app in _declared_debs().items():
        for arch, url in app["url"].items():
            assert url in desktop_sh, f"desktop.sh missing {name}/{arch} URL"
            assert app["sha256"][arch] in desktop_sh, f"desktop.sh missing {name}/{arch} digest"
    assert "download_verified_file" in desktop_sh, (
        "desktop.sh must use rldyour::download_verified_file, not a bare download"
    )
    assert "cdn.browseros.com" not in desktop_sh, (
        "desktop.sh must not reference the volatile CDN latest pointer"
    )


def test_the_release_host_check_rejects_a_lookalike_domain() -> None:
    """A substring test admitted `github.com.attacker.example`; the parsed-host
    test must not. Verified directly rather than trusted."""
    for hostile in (
        "https://github.com.attacker.example/o/r/releases/download/1.0/a.deb",
        "https://attacker.example/x?ref=github.com",
        "http://github.com/o/r/releases/download/1.0/a.deb",
    ):
        parsed = urlparse(hostile)
        assert not (parsed.scheme == "https" and parsed.hostname == "github.com"), hostile
    good = "https://github.com/o/r/releases/download/1.0/a.deb"
    parsed = urlparse(good)
    assert parsed.scheme == "https" and parsed.hostname == "github.com"
