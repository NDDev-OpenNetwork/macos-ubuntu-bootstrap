"""Go and Rust are desktop-only language-server hosts.

They back gopls and rust-analyzer over the estate's Go and Rust sources. The
Ubuntu server profile is `container-execution-only`, so a host compiler there
would restore exactly the local build capability that policy removes — project
builds belong in Docker. These tests pin that split, and pin the tracked
artifact provenance so a version bump cannot silently drop a hash.
"""

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts/bootstrap.sh"
INSTALL = ROOT / "scripts/ubuntu/install.sh"
CONTRACT = json.loads((ROOT / "config/rldyour-contract.json").read_text(encoding="utf-8"))
RUNTIME = CONTRACT["runtime_support"]


def plan(profile: str) -> str:
    """Render an Ubuntu plan. The harness layer is skipped so the plan does not
    depend on whether this machine already owns a managed harness target."""
    result = subprocess.run(
        [
            "bash", str(BOOTSTRAP),
            "--platform", "ubuntu",
            "--profile", profile,
            "--skip-ai",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "RLDYOUR_DRY_RUN": "1"},
    )
    return result.stdout + result.stderr


def test_desktop_plans_go_and_rust_hosts() -> None:
    output = plan("desktop")
    assert f"Ensure Go {RUNTIME['ubuntu_go']}" in output
    assert f"Ensure Rust {RUNTIME['ubuntu_rust']}" in output
    assert RUNTIME["ubuntu_gopls"] in output
    assert "rust-analyzer" in output


def test_server_never_plans_a_host_compiler() -> None:
    output = plan("server")
    assert "compiled-language LSP hosts skipped" in output
    assert f"Ensure Go {RUNTIME['ubuntu_go']}" not in output
    assert f"Ensure Rust {RUNTIME['ubuntu_rust']}" not in output


def test_contract_tracks_a_hash_for_every_supported_architecture() -> None:
    assert set(RUNTIME["ubuntu_go_sha256"]) == {"amd64", "arm64"}
    assert set(RUNTIME["ubuntu_rust_sha256"]) == {"x86_64", "aarch64"}
    for digests in (RUNTIME["ubuntu_go_sha256"], RUNTIME["ubuntu_rust_sha256"]):
        for arch, digest in digests.items():
            assert re.fullmatch(r"[0-9a-f]{64}", digest), f"{arch} digest is not a sha256"


def test_installer_constants_match_the_contract() -> None:
    """The contract is the declared truth; the installer must not drift from it."""
    source = INSTALL.read_text(encoding="utf-8")

    def constant(name: str) -> str:
        match = re.search(rf'^{name}="([^"]+)"', source, re.M)
        assert match, f"{name} missing from the Ubuntu installer"
        return match.group(1)

    assert constant("GO_VERSION") == RUNTIME["ubuntu_go"]
    assert constant("GOPLS_VERSION") == RUNTIME["ubuntu_gopls"]
    assert constant("RUST_VERSION") == RUNTIME["ubuntu_rust"]
    assert constant("RUST_CHANNEL_DATE") == RUNTIME["ubuntu_rust_channel_date"]
    assert constant("GO_SHA256_AMD64") == RUNTIME["ubuntu_go_sha256"]["amd64"]
    assert constant("GO_SHA256_ARM64") == RUNTIME["ubuntu_go_sha256"]["arm64"]
    assert constant("RUST_SHA256_X86_64") == RUNTIME["ubuntu_rust_sha256"]["x86_64"]
    assert constant("RUST_SHA256_AARCH64") == RUNTIME["ubuntu_rust_sha256"]["aarch64"]


def _pinned_rows() -> list[list[str]]:
    source = INSTALL.read_text(encoding="utf-8")
    block = re.search(r"^PINNED_SOURCE_TOOLS=\((.*?)^\)", source, re.M | re.S)
    assert block, "PINNED_SOURCE_TOOLS table missing"
    return [
        line.strip().strip('"').split(";")
        for line in block.group(1).splitlines()
        if line.strip().startswith('"')
    ]


def test_pinned_tool_rows_are_well_formed() -> None:
    """The table is the only way to add a pinned tool, so a malformed row must
    fail here rather than half-install on a real device."""
    rows = _pinned_rows()
    assert rows, "no pinned source tools declared"
    seen = set()
    for row in rows:
        assert len(row) == 10, f"row must have 10 fields, got {len(row)}: {row[:1]}"
        name, version, kind, m_x64, m_arm64, links, sha_x64, sha_arm64, u_x64, u_arm64 = row
        assert name not in seen, f"duplicate tool {name}"
        seen.add(name)
        assert kind in {"tar0", "tar1", "zip", "raw"}, f"{name}: unknown kind {kind}"
        for digest in (sha_x64, sha_arm64):
            assert re.fullmatch(r"[0-9a-f]{64}", digest), f"{name}: bad sha256"
        assert sha_x64 != sha_arm64, f"{name}: both architectures share one digest"
        for url in (u_x64, u_arm64):
            assert url.startswith("https://"), f"{name}: non-https artifact URL"
        assert u_x64 != u_arm64, f"{name}: both architectures share one URL"
        # members and links must stay parallel, or the installer links the wrong file
        assert len(m_x64.split(",")) == len(links.split(",")), f"{name}: members/links mismatch"
        assert len(m_arm64.split(",")) == len(links.split(",")), f"{name}: members/links mismatch"
        # the version must appear in at least one URL, so a bumped pin cannot
        # keep pointing at the previous artifact
        assert version in u_x64 or version.replace(".", "") in u_x64, (
            f"{name}: version {version} does not appear in its x64 URL"
        )


def test_pinned_tools_match_the_contract() -> None:
    declared = RUNTIME["ubuntu_pinned_source_tools"]
    rows = {row[0]: row for row in _pinned_rows()}
    assert set(declared) == set(rows), "contract and installer disagree on the tool set"
    for name, row in rows.items():
        assert declared[name]["version"] == row[1], f"{name}: version drift"
        assert declared[name]["sha256"]["x64"] == row[6], f"{name}: x64 digest drift"
        assert declared[name]["sha256"]["arm64"] == row[7], f"{name}: arm64 digest drift"


def test_pinned_tools_are_verified_on_desktop_only() -> None:
    """Every pinned tool must be gated, and gated inside the desktop-only block —
    the server profile is container-execution-only and gets none of them."""
    verify = (ROOT / "scripts/ubuntu/verify.sh").read_text(encoding="utf-8")
    desktop_block = verify.split('if [ "$PROFILE" = "desktop" ]; then', 1)
    assert len(desktop_block) == 2, "desktop-only block not found in verify.sh"
    for row in _pinned_rows():
        for link in row[5].split(","):
            assert link in desktop_block[1], f"{link} is installed but never verified"


def test_ast_grep_does_not_publish_the_deprecated_sg_shim() -> None:
    """ast-grep's archive ships an `sg` shim that upstream deprecated and that
    would shadow util-linux's setgid `sg` on hosts that have it."""
    row = next(r for r in _pinned_rows() if r[0] == "ast-grep")
    assert "sg" not in row[5].split(","), "the deprecated sg shim must not be published"


def test_gopls_provenance_is_declared_and_not_a_tracked_hash() -> None:
    """gopls ships no prebuilt archive. Its provenance is the Go module checksum
    database, and that difference must stay explicit rather than look like an
    oversight in the hash table."""
    assert RUNTIME["ubuntu_gopls_provenance"] == "go-module-checksum-database"
    source = INSTALL.read_text(encoding="utf-8")
    assert "GOSUMDB=sum.golang.org" in source
    assert "GOFLAGS=-mod=readonly" in source
