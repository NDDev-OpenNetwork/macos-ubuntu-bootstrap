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


def test_gopls_provenance_is_declared_and_not_a_tracked_hash() -> None:
    """gopls ships no prebuilt archive. Its provenance is the Go module checksum
    database, and that difference must stay explicit rather than look like an
    oversight in the hash table."""
    assert RUNTIME["ubuntu_gopls_provenance"] == "go-module-checksum-database"
    source = INSTALL.read_text(encoding="utf-8")
    assert "GOSUMDB=sum.golang.org" in source
    assert "GOFLAGS=-mod=readonly" in source
