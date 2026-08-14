"""Contract parity tests: the contract JSON must match the installer code.

Extends the pattern established by test_compiled_language_hosts.py
(test_installer_constants_match_the_contract) to cover the domains that were
previously unchecked: apt baseline, GUI applications, macOS GUI casks, and
Node/uv/Bun version+hash constants. A drift between the contract and the
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
MACOS_VERIFY = (ROOT / "scripts/macos/verify.sh").read_text(encoding="utf-8")


def test_release_metadata_matches_contract_version() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert CONTRACT["adapter"]["version"] == version
    assert f"## Contract {version}" in agents
    assert f"current contract is `{version}`" in readme
    assert re.search(rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.M)


def test_ubuntu_gui_architecture_boundary_is_explicit_and_enforced() -> None:
    ubuntu = CONTRACT["targets"]["ubuntu"]
    assert ubuntu["architectures"] == ["amd64", "arm64"]
    assert ubuntu["gui_architectures"] == ["amd64"]
    assert 'if [ "$RLDYOUR_DRY_RUN" -eq 0 ] && [ "$GUI_ENABLED" -eq 1 ]' in UBUNTU_INSTALL
    assert "Google Chrome and Telegram Desktop publish no supported Linux ARM64 build" in UBUNTU_INSTALL


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
        # Herdr uses the canonical per-platform source asset table; Telegram
        # uses a single archive_sha256.
        if name == "herdr":
            assets = spec["source"]["assets"]
            assert row[6] == assets["linux-x86_64"]["sha256"], f"{name}: x64 SHA-256 drift"
            assert row[7] == assets["linux-aarch64"]["sha256"], f"{name}: arm64 SHA-256 drift"
            assert row[8] == assets["linux-x86_64"]["url"], f"{name}: x64 URL drift"
            assert row[9] == assets["linux-aarch64"]["url"], f"{name}: arm64 URL drift"
        elif "archive_sha256" in spec:
            assert row[6] == spec["archive_sha256"], f"{name}: archive SHA-256 drift"
            assert row[7] in {"", spec["archive_sha256"]}, f"{name}: archive SHA-256 (arm64 slot) drift"


def test_macos_herdr_asset_matches_contract_and_bypasses_homebrew() -> None:
    herdr = CONTRACT["user_tools"]["herdr"]
    macos = herdr["source"]["assets"]["macos-aarch64"]
    assert herdr["install_method"]["macos"] == "verified-github-release-binary"
    assert _constant(MACOS_INSTALL, "HERDR_VERSION") == herdr["version"]
    assert _constant(MACOS_INSTALL, "HERDR_MACOS_AARCH64_SHA256") == macos["sha256"]
    assert _constant(MACOS_INSTALL, "HERDR_MACOS_AARCH64_URL") == macos["url"]
    assert _constant(MACOS_VERIFY, "HERDR_VERSION") == herdr["version"]
    assert _constant(MACOS_VERIFY, "HERDR_MACOS_AARCH64_SHA256") == macos["sha256"]
    assert _constant(MACOS_VERIFY, "HERDR_MACOS_AARCH64_URL") == macos["url"]
    assert "herdr" not in _parse_bash_array(MACOS_INSTALL, "BREW_SOURCE_PACKAGES")
    assert "ensure_herdr" in MACOS_INSTALL.split("main() {", 1)[1]
    assert herdr["source"]["tag"] == f"v{herdr['version']}"
    assert herdr["source"]["tag_object"] == "857196dee1ce98df53efdd3f437aa2ac8a75b608"
    assert herdr["source"]["commit"] == "346411fa21afd297f5ed3b3fa56f9e3fbf7654b7"
    assert herdr["source"]["verified_at"] == "2026-08-13"
    assert "never invoke mutable herdr update" in herdr["update_policy"]
    assert "herdr update" not in MACOS_INSTALL


# ---------- desktop entries, GUI fonts, and launcher preconditions ----------


def _gui_capable_profiles() -> list[str]:
    """Profiles whose contract allows gui_modes to be enabled."""
    profiles = CONTRACT["targets"]["ubuntu"]["profiles"]
    return sorted(
        name for name, spec in profiles.items() if "enabled" in spec["gui_modes"]
    )


def test_desktop_entries_cover_every_gui_capable_profile() -> None:
    """install_desktop_entries is gated on GUI, not on profile.

    The contract listed only `desktop`, so a desktop-builds workstation with a
    GUI installed both launchers while the contract said it should not -- and
    no test could see the disagreement. desktop-builds is everything desktop
    has plus Docker (ADR 0008), and user_tools.telegram already declared both.
    """
    expected = _gui_capable_profiles()
    for name, entry in CONTRACT["desktop_entries"].items():
        assert sorted(entry["profiles"]) == expected, (
            f"desktop entry {name} does not match the GUI-capable profile set"
        )


def test_desktop_entries_are_installed_for_any_gui_profile() -> None:
    """The installer's gate must be the one the contract describes."""
    body = UBUNTU_INSTALL.split("install_desktop_entries() {", 1)[1].split("\n}", 1)[0]
    assert '[ "$GUI_ENABLED" -eq 1 ]' in body
    # $PROFILE appears only in the skip message, never as a condition.
    assert '[ "$PROFILE"' not in body, (
        "the installer gates desktop entries on GUI alone; the contract must say so"
    )


def test_gui_fonts_are_declared_rather_than_inlined() -> None:
    declared = CONTRACT["ubuntu_apt_packages"]["desktop_gui_fonts"]
    block = re.search(r"^APT_DESKTOP_GUI_FONTS=\((.*?)\)", UBUNTU_INSTALL, re.M | re.S)
    assert block, "APT_DESKTOP_GUI_FONTS is missing"
    assert block.group(1).split() == declared, "GUI font set drifts from the contract"
    assert 'apt_install fonts-jetbrains-mono' not in UBUNTU_INSTALL, (
        "a bare literal install is invisible to package parity"
    )


def test_every_desktop_entry_declares_a_runnable_precondition() -> None:
    """A launcher whose program is absent must hide, not fail silently.

    herdr.desktop runs Ptyxis, which nothing here installs and which Ubuntu
    24.04 does not package; without TryExec the entry appears in the menu and
    starts nothing.
    """
    for name, entry in CONTRACT["desktop_entries"].items():
        template = ROOT / entry["source"]
        text = template.read_text(encoding="utf-8")
        exec_lines = [
            line for line in text.splitlines() if line.startswith("Exec=")
        ]
        assert exec_lines, f"{name}: no Exec line"
        try_exec = [line for line in text.splitlines() if line.startswith("TryExec=")]
        assert len(try_exec) == 1, f"{name}: exactly one TryExec is required"
        program = try_exec[0].removeprefix("TryExec=").strip()
        assert program, f"{name}: empty TryExec"
        first = exec_lines[0].removeprefix("Exec=").split()
        # `Exec=env VAR=value program ...` is the managed Telegram shape.
        while first and ("=" in first[0] or first[0] == "env"):
            first = first[1:]
        assert first and Path(first[0]).name == Path(program).name, (
            f"{name}: TryExec {program} does not guard Exec {exec_lines[0]}"
        )


UBUNTU_VERIFY = (ROOT / "scripts/ubuntu/verify.sh").read_text(encoding="utf-8")


def test_ubuntu_verifier_asserts_the_contract_versions() -> None:
    """Every version the Ubuntu verifier asserts must come from the contract.

    The parity tests above bind the *installer* constants. Nothing bound the
    *verifier*, and the two drifted apart in exactly the way that is hardest to
    see: `uv`'s check is a regex with escaped dots, so a refresh that rewrites
    every literal `0.11.30` in the tree leaves `'^uv 0\\.11\\.30…'` untouched.
    The installer would then publish one version and the verifier demand
    another, and a strict verify would fail on a correctly installed host.

    Each assertion below is written the way that verifier writes it, so a pin
    refresh that misses one fails here rather than on a device.
    """
    runtime = CONTRACT["runtime_support"]
    node = runtime["ubuntu_node_lts"]
    uv = runtime["ubuntu_uv"]
    bun = runtime["ubuntu_bun"]
    go = runtime["ubuntu_go"]
    rust = runtime["ubuntu_rust"]
    dart = runtime["ubuntu_dart"]

    # Exact-match command probes.
    assert f'"$(node --version 2>/dev/null | head -n 1)" = "v{node}"' in UBUNTU_VERIFY
    assert f'"$(bun --version 2>/dev/null | head -n 1)" = "{bun}"' in UBUNTU_VERIFY
    assert f"= \"go{go}\"" in UBUNTU_VERIFY
    assert f"= \"{rust}\"" in UBUNTU_VERIFY
    assert f"= \"{dart}\"" in UBUNTU_VERIFY

    # uv reports `uv X.Y.Z (<commit> <date>)`, so its check is a regex and its
    # dots are escaped. Rebuild that exact pattern from the contract.
    uv_pattern = "grep -Eq '^uv {}([[:space:]]|$)'".format(uv.replace(".", r"\."))
    assert uv_pattern in UBUNTU_VERIFY, f"verifier does not assert uv {uv}"

    # Managed runtime receipts carry the version as a bare argument.
    assert f"runtime_receipt node {node} " in UBUNTU_VERIFY
    assert f"runtime_receipt uv {uv} " in UBUNTU_VERIFY
    assert f"runtime_receipt bun {bun} " in UBUNTU_VERIFY

    # Managed install roots are versioned paths; a stale root would verify a
    # directory the installer never creates.
    assert f'node_root="$HOME/.local/share/rldyour/node/v{node}"' in UBUNTU_VERIFY
    assert f'uv_root="$HOME/.local/share/rldyour/uv/{uv}"' in UBUNTU_VERIFY
    assert f'bun_root="$HOME/.local/share/rldyour/bun/{bun}"' in UBUNTU_VERIFY


def test_no_stale_runtime_version_survives_anywhere_in_the_verifier() -> None:
    """No version-shaped literal in the verifier is outside the contract.

    The test above proves the current pins are asserted. This one proves no
    *previous* pin is still asserted somewhere else in the same file — the
    failure mode where a refresh updates one of two call sites.
    """
    runtime = CONTRACT["runtime_support"]
    known = {
        runtime["ubuntu_node_lts"],
        runtime["ubuntu_uv"],
        runtime["ubuntu_bun"],
        runtime["ubuntu_go"],
        runtime["ubuntu_rust"],
        runtime["ubuntu_dart"],
        CONTRACT["user_tools"]["herdr"]["version"],
    }
    # Escaped-regex spellings of the same versions are equally valid.
    known |= {v.replace(".", r"\.") for v in known}

    found = set(re.findall(r"\b\d+\\?\.\d+\\?\.\d+\b", UBUNTU_VERIFY))
    stale = found - known
    assert not stale, f"verifier asserts versions absent from the contract: {sorted(stale)}"


# --------------------------------------------------------------------------
# macOS package determinism (#63, ADR 0010)
#
# The Homebrew set resolves by bare name, so one release yields different tool
# versions depending on host history. That was never a taken decision, and the
# provenance schema documented the opposite of it. ADR 0010 takes the decision;
# these tests bind it to the installer so a package cannot be added without one.
# --------------------------------------------------------------------------


def _macos_array(name: str) -> list[str]:
    match = re.search(rf"^{name}=\(\n(.*?)^\)", MACOS_INSTALL, re.S | re.M)
    if match:
        return re.sub(r"#.*$", "", match.group(1), flags=re.M).split()
    match = re.search(rf"^{name}=\((.*?)\)$", MACOS_INSTALL, re.M)
    assert match, f"{name} not found in scripts/macos/install.sh"
    return match.group(1).split()


def test_every_macos_formula_and_cask_has_a_determinism_class() -> None:
    block = CONTRACT["macos_package_determinism"]
    assert set(_macos_array("BREW_SOURCE_PACKAGES")) == set(block["rolling-homebrew-formula"])
    assert set(_macos_array("GUI_CASKS")) == set(block["rolling-homebrew-cask"])


def test_every_declared_class_is_defined_and_non_empty() -> None:
    block = CONTRACT["macos_package_determinism"]
    defined = set(block["classes"])
    populated = {
        key for key in block
        if not key.startswith("_") and key not in {"classes", "provenance_may_declare",
                                                   "provenance_must_not_declare"}
    }
    assert populated == defined, f"class keys and definitions disagree: {populated ^ defined}"
    for name in defined:
        assert block[name], f"{name} is declared but empty"
        assert len(block["classes"][name]) > 40, f"{name} has no usable definition"


def test_no_package_is_classified_twice() -> None:
    block = CONTRACT["macos_package_determinism"]
    seen: set[str] = set()
    for name in block["classes"]:
        members = set(block[name])
        assert not (members & seen), f"{name} re-classifies {sorted(members & seen)}"
        seen |= members


def test_the_registry_pinned_class_holds_exact_versions() -> None:
    """A registry-pinned entry without a version is a rolling entry in disguise."""
    block = CONTRACT["macos_package_determinism"]
    lsp = set(_macos_array("BUN_LSP_PACKAGES")) if "BUN_LSP_PACKAGES=(" in MACOS_INSTALL else set()
    lsp = {item.strip('"') for item in lsp}
    for entry in block["registry-pinned"]:
        if entry == "@openai/codex":
            continue  # pinned by version + sha512 in harnesses, not by an npm spec
        assert "@" in entry.lstrip("@"), f"{entry} names no version"
        assert entry in lsp, f"{entry} is classified but not in BUN_LSP_PACKAGES"


def test_the_exact_class_covers_what_must_not_come_from_homebrew() -> None:
    """Herdr and Homebrew itself are exact, and deliberately not formulae."""
    block = CONTRACT["macos_package_determinism"]
    exact = set(block["immutable-upstream-artifact"])
    assert {"herdr", "homebrew-pkg"} <= exact
    # Herdr must not also be a formula: AGENTS.md forbids substituting the
    # Homebrew formula for the receipt-pinned release asset.
    assert "herdr" not in set(_macos_array("BREW_SOURCE_PACKAGES"))
    assert CONTRACT["user_tools"]["herdr"]["install_method"]["macos"] == (
        "verified-github-release-binary"
    )


def test_provenance_may_not_declare_what_no_resolver_can_check() -> None:
    """The five-tuple that read as a guarantee and was never read.

    Each forbidden field carries the reason it is forbidden, so a future change
    has to argue with the reason rather than just re-add the field.
    """
    block = CONTRACT["macos_package_determinism"]
    forbidden = block["provenance_must_not_declare"]
    for field in ("formula_revision", "bottle_tag", "bottle_rebuild",
                  "bottle_sha256", "executable_sha256"):
        assert field in forbidden, f"{field} is not recorded as forbidden"
        assert len(forbidden[field]) > 30, f"{field} is forbidden without a reason"
    assert not set(forbidden) & set(block["provenance_may_declare"])


def test_the_adr_exists_and_is_cited_by_the_contract() -> None:
    """A citation that resolves to nothing is a defect, per docs/adr/README.md."""
    referenced = CONTRACT["macos_package_determinism"]["_adr"]
    assert (ROOT / referenced).is_file(), f"contract cites a missing ADR: {referenced}"
    adr = (ROOT / referenced).read_text(encoding="utf-8")
    assert adr.startswith("# ADR 0010:")
    assert "Status: accepted" in adr
