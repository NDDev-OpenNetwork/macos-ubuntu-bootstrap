"""Go, Rust, and Dart are desktop-only language-server hosts.

They back gopls, rust-analyzer, and the Dart analysis server over the estate's
sources. The Ubuntu server profile is `container-execution-only`, so a host
toolchain there would restore exactly the local build capability that policy
removes — project builds belong in Docker. These tests pin that split, and pin the
tracked artifact provenance so a version bump cannot silently drop a hash.

Dart carries a second obligation (ADR 0006): the same archive provides the
`dart mcp-server` transport that the rldyour-mcps `dart-flutter` server executes,
so the host is what makes a declared MCP server startable at all.
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


def test_desktop_plans_go_rust_and_dart_hosts() -> None:
    output = plan("desktop")
    assert f"Ensure Go {RUNTIME['ubuntu_go']}" in output
    assert f"Ensure Rust {RUNTIME['ubuntu_rust']}" in output
    assert f"Ensure Dart {RUNTIME['ubuntu_dart']}" in output
    assert RUNTIME["ubuntu_gopls"] in output
    assert "rust-analyzer" in output


def test_server_never_plans_a_host_compiler() -> None:
    output = plan("server")
    assert "compiled-language LSP hosts skipped" in output
    assert f"Ensure Go {RUNTIME['ubuntu_go']}" not in output
    assert f"Ensure Rust {RUNTIME['ubuntu_rust']}" not in output
    assert f"Ensure Dart {RUNTIME['ubuntu_dart']}" not in output


def test_contract_tracks_a_hash_for_every_supported_architecture() -> None:
    assert set(RUNTIME["ubuntu_go_sha256"]) == {"amd64", "arm64"}
    assert set(RUNTIME["ubuntu_rust_sha256"]) == {"x86_64", "aarch64"}
    assert set(RUNTIME["ubuntu_dart_sha256"]) == {"x64", "arm64"}
    for digests in (
        RUNTIME["ubuntu_go_sha256"],
        RUNTIME["ubuntu_rust_sha256"],
        RUNTIME["ubuntu_dart_sha256"],
    ):
        for arch, digest in digests.items():
            assert re.fullmatch(r"[0-9a-f]{64}", digest), f"{arch} digest is not a sha256"


def test_dart_tree_permissions_are_normalized_and_revalidated() -> None:
    """The Dart SDK zip records its directories as 0775 and umask only clears bits
    it never adds, so a naive extraction publishes group-writable directories
    inside a receipt-verified tree. The receipt hashes only the declared
    executables, so a writable directory beside them is enough to add or swap a
    snapshot without invalidating it. Both the fresh and the reused path must go
    through the shared permission helper."""
    install = INSTALL.read_text(encoding="utf-8")
    common = (ROOT / "scripts/lib/common.sh").read_text(encoding="utf-8")
    dart = install.split("ensure_dart()", 1)[1].split("\nensure_bun()", 1)[0]
    assert 'rldyour::_managed_tree_permissions normalize "$stage/prefix"' in dart
    assert 'rldyour::_managed_tree_permissions validate "$destination"' in dart
    # One generic helper, not a second permission path bolted on for Dart.
    assert "rldyour::_browser_node_runtime_permissions" not in common
    assert common.count("rldyour::_managed_tree_permissions() {") == 1


def test_rust_tree_is_permission_normalized_before_its_receipt() -> None:
    """Rust's bundled install.sh creates its prefix under the caller's umask, so
    `umask 002` published a tree whose root was 0775. Go and Node avoid this only
    because their trees come from `mktemp -d` at 0700, which is luck rather than a
    guarantee. The receipt covers five executables, so a writable directory beside
    them is enough to add a library without invalidating it.

    Node's `npm`/`npx`/`corepack` entries look group-writable to `find -perm /022`
    but are symlinks, whose mode bits Linux ignores; the shared helper skips
    symlinks after checking containment, so it is a no-op there by design."""
    install = INSTALL.read_text(encoding="utf-8")
    rust = install.split("ensure_rust()", 1)[1].split("\n# Dart SDK host", 1)[0]
    normalize = rust.index('rldyour::_managed_tree_permissions normalize "$stage/prefix"')
    receipt = rust.index("rldyour::ubuntu::write_runtime_receipt")
    assert normalize < receipt, "the tree must be normalized before its receipt is written"


def test_dart_telemetry_is_disabled_through_one_shared_fail_closed_helper() -> None:
    """The SDK reports telemetry by default, which contradicts the same boundary
    that makes the browser wrapper reject usage statistics. The opt-out must be
    set through the SDK's own switch (the config is upstream-maintained, never
    hand-written), proven rather than assumed, and shared by both platforms."""
    common = (ROOT / "scripts/lib/common.sh").read_text(encoding="utf-8")
    assert "rldyour::ensure_dart_telemetry_disabled() {" in common
    assert '"$binary" --disable-analytics' in common
    # Proven, not assumed: a conflicting enable line fails instead of being
    # averaged away by upstream duplicate-key resolution.
    assert "grep -Fxq 'reporting=0'" in common
    assert "grep -Fxq 'reporting=1'" in common
    for installer in ("scripts/ubuntu/install.sh", "scripts/macos/install.sh"):
        body = (ROOT / installer).read_text(encoding="utf-8")
        assert "rldyour::ensure_dart_telemetry_disabled" in body, installer
    # The config is never written by this repository, only read back.
    assert "dart-flutter-telemetry.config" in common
    assert "reporting=0\\n" not in common
    verify = (ROOT / "scripts/ubuntu/verify.sh").read_text(encoding="utf-8")
    assert "dart-flutter-telemetry.config" in verify


def test_dart_host_serves_both_the_analysis_server_and_the_mcp_transport() -> None:
    """ADR 0006. The reason Dart is admitted is that one archive backs source
    analysis and the `dart-flutter` MCP server. Verification must prove the
    subcommand exists, not just that a `dart` binary resolves — an SDK that
    resolves but cannot serve MCP is the exact defect this replaced."""
    assert RUNTIME["ubuntu_dart_provides"] == [
        "dart",
        "dart language-server",
        "dart mcp-server",
    ]
    install = INSTALL.read_text(encoding="utf-8")
    # Flutter is deliberately absent: its bin/cache self-populates at runtime and
    # would mutate a receipt-verified tree.
    assert "flutter_linux" not in install
    for verifier in ("scripts/ubuntu/verify.sh", "scripts/macos/verify.sh"):
        body = (ROOT / verifier).read_text(encoding="utf-8")
        assert "dart mcp-server --version" in body, f"{verifier} does not prove the MCP transport"
    ubuntu_verify = (ROOT / "scripts/ubuntu/verify.sh").read_text(encoding="utf-8")
    desktop_block = ubuntu_verify.split('if [ "$PROFILE" != "server" ]; then', 1)
    assert len(desktop_block) == 2
    assert "dart" in desktop_block[1], "dart must be verified inside the non-server block"


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
    assert constant("DART_VERSION") == RUNTIME["ubuntu_dart"]
    assert constant("DART_SHA256_X64") == RUNTIME["ubuntu_dart_sha256"]["x64"]
    assert constant("DART_SHA256_ARM64") == RUNTIME["ubuntu_dart_sha256"]["arm64"]


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
    """Every pinned tool must be gated inside the non-server block —
    the server profile is container-execution-only and gets none of them."""
    verify = (ROOT / "scripts/ubuntu/verify.sh").read_text(encoding="utf-8")
    desktop_block = verify.split('if [ "$PROFILE" != "server" ]; then', 1)
    assert len(desktop_block) == 2, "non-server block not found in verify.sh"
    for row in _pinned_rows():
        for link in row[5].split(","):
            assert link in desktop_block[1], f"{link} is installed but never verified"


def test_user_tools_are_verified_on_desktop_only() -> None:
    """Every USER_TOOLS entry must be verified inside the non-server block."""
    verify = (ROOT / "scripts/ubuntu/verify.sh").read_text(encoding="utf-8")
    desktop_block = verify.split('if [ "$PROFILE" != "server" ]; then', 1)
    assert len(desktop_block) == 2, "non-server block not found in verify.sh"
    install = INSTALL.read_text(encoding="utf-8")
    match = re.search(r'USER_TOOLS=\(\s*(.*?)\)', install, re.DOTALL)
    assert match is not None, "USER_TOOLS array not found"
    for raw in re.findall(r'"([^"]+)"', match.group(1)):
        fields = raw.split(";")
        name, link = fields[0], fields[5]
        assert link in desktop_block[1], (
            f"{name} ({link}) is installed via USER_TOOLS but never verified"
        )



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
