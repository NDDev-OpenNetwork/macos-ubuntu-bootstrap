import hashlib
import json
import os
import re
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_shell(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/bootstrap.sh", *args],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


def file(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def parse_array(body: str, name: str) -> set[str]:
    match = re.search(
        rf"^\s*{re.escape(name)}=\((.*?)\)", body, re.MULTILINE | re.DOTALL
    )
    assert match is not None, f"{name} array not found"
    values: list[str] = []
    for quoted_double, quoted_single, bare in re.findall(
        r'"([^"]+)"|\'([^\']+)\'|([^\s#]+)', match.group(1)
    ):
        value = quoted_double or quoted_single or bare
        if value:
            values.append(value)
    return set(values)


def test_help_documents_composed_profiles() -> None:
    result = run_shell("--help")
    assert result.returncode == 0
    assert "--gui|--no-gui" in result.stdout
    assert "--docker-mode none|rootful|rootless" in result.stdout
    assert "source editing" in result.stdout
    assert "CloakBrowser" in result.stdout


def test_plan_matrix_is_non_destructive() -> None:
    common = ("--plan", "--skip-system", "--skip-ai", "--skip-lsps", "--skip-checks")
    matrix = (
        ("--platform", "macos", "--profile", "desktop", "--gui"),
        ("--platform", "macos", "--profile", "desktop", "--no-gui"),
        ("--platform", "ubuntu", "--profile", "desktop", "--gui"),
        ("--platform", "ubuntu", "--profile", "desktop", "--no-gui"),
        ("--platform", "ubuntu", "--profile", "server", "--docker-mode", "rootful"),
        ("--platform", "ubuntu", "--profile", "server", "--docker-mode", "rootless"),
    )
    for profile in matrix:
        result = run_shell(*profile, *common)
        assert result.returncode == 0, result.stderr + result.stdout
        assert "dry-run" in result.stdout
        assert "CloakBrowser" in result.stdout
        # NOTE: the server-layer dispatch assertion lived here but was vacuously
        # true under --skip-system (run_server_layer returns at the SKIP_SYSTEM
        # guard before printing anything). The meaningful server-vs-desktop
        # dispatch test is in test_profile_isolation.py, which runs plan mode
        # WITHOUT --skip-system to prove the server layer header appears for
        # server and is absent for desktop.


def test_skip_system_covers_ubuntu_server_layer() -> None:
    ubuntu = file("scripts/ubuntu/install.sh")
    match = re.search(
        r"^run_server_layer\(\) \{(.*?)(?=^\w[^\n]*\(\) \{)",
        ubuntu,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None
    body = match.group(1)
    guard = 'if [ "$SKIP_SYSTEM" -eq 1 ]; then'
    assert guard in body
    assert body.index(guard) < body.index("is_supported_ubuntu")


def test_managed_scripts_avoid_ambiguous_and_or_control_flow() -> None:
    ambiguous = re.compile(r"\]\s*&&\s*\[[^\n]*\]\s*\|\|\s*\{")
    for path in sorted((ROOT / "scripts").rglob("*.sh")):
        body = path.read_text(encoding="utf-8")
        assert not ambiguous.search(body), f"ambiguous A && B || fallback in {path}"


def test_invalid_profile_combinations_fail_closed() -> None:
    invalid = (
        ("--platform", "ubuntu"),
        ("--platform", "macos", "--profile", "server"),
        ("--platform", "ubuntu", "--profile", "server", "--gui"),
        ("--platform", "ubuntu", "--profile", "desktop", "--docker-mode", "rootful"),
        ("--platform", "ubuntu", "--skip-browser"),
    )
    for args in invalid:
        result = run_shell(*args, "--plan")
        assert result.returncode != 0


def test_contract_version_and_profile_matrix() -> None:
    contract = json.loads(file("config/rldyour-contract.json"))
    assert contract["schema_version"] == 2
    version = file("VERSION").strip()
    assert contract["adapter"]["version"] == version
    assert (
        json.loads(file("templates/browser/provider/package.json"))["version"]
        == version
    )
    assert f'version = "{version}"' in file(
        "templates/browser/cloakbrowser-pyproject.toml"
    )
    assert f'version = "{version}"' in file("templates/browser/cloakbrowser-uv.lock")
    for path in (
        "README.md",
        "AGENTS.md",
        ".claude/CLAUDE.md",
        "docs/install.md",
        "SECURITY.md",
    ):
        assert version in file(path), f"{path} missing adapter version {version}"
    assert contract["targets"]["macos"]["architectures"] == ["arm64"]
    assert contract["targets"]["ubuntu"]["releases"] == ["24.04", "26.04"]
    assert (
        contract["targets"]["ubuntu"]["profiles"]["server"]["default_docker_mode"]
        == "rootful"
    )
    assert contract["targets"]["ubuntu"]["profiles"]["desktop"]["docker_modes"] == [
        "none"
    ]
    assert {"chatgpt", "codex-app"}.issubset(contract["gui"]["macos"])
    assert contract["runtime_support"]["ubuntu_node_lts"] == "24.18.0"
    assert set(contract["runtime_support"]["ubuntu_node_sha256"]) == {"x64", "arm64"}
    assert contract["runtime_support"]["ubuntu_uv"] == "0.11.30"
    assert contract["runtime_support"]["ubuntu_bun"] == "1.3.14"
    assert contract["safety"]["ubuntu_profile_selection"] == "explicit"


def test_active_harness_set_is_only_codex() -> None:
    # RVR-P1-004: one owner per harness. Claude Code, OpenCode, MiMoCode, and
    # Antigravity are fully removed; codex is delegated to its authoritative NDDev
    # module. ADR 0006 moved zcode out of bootstrap: the ZCode app owns ~/.zcode
    # and its installer needs an explicit --adopt-unmanaged that no unattended run
    # may supply, so blocking a device apply on it stranded every later layer.
    contract = json.loads(file("config/rldyour-contract.json"))
    assert "ai_cli" not in contract
    harnesses = contract["harnesses"]
    assert harnesses["policy"] == "one-owner-per-harness"
    assert harnesses["active"] == ["codex"]
    assert harnesses["codex"]["module_path_env"] == "RLDYOUR_CODEX_MODULE"
    assert harnesses["codex"]["module_repo"].endswith("nddev-codex-app.git")
    assert len(harnesses["codex"]["module_commit"]) == 40
    # The delegation stays declared, so it reads as a decision, not an omission.
    delegated = harnesses["delegated"]
    assert delegated["zcode"]["owner_repo"] == "nddev-harnesses"
    assert delegated["zcode"]["reason"]
    assert "zcode" not in harnesses["active"]

    installers = (file("scripts/macos/install.sh"), file("scripts/ubuntu/install.sh"))
    removed_constants = (
        "CLAUDE_CODE_VERSION",
        "OPENCODE_VERSION",
        "MIMOCODE_VERSION",
        "ANTIGRAVITY_VERSION",
        "ZCODE_VERSION",
    )
    for body in installers:
        for name in removed_constants:
            assert f"{name}=" not in body, f"stale harness constant {name}"
        assert "rldyour::install_selected_harnesses" in body

    # No harness is installed through a bun/npm global path.
    for body in installers:
        for package in (
            "@anthropic-ai/claude-code",
            "opencode-ai",
            "@mimo-ai/cli",
            "@openai/codex",
        ):
            assert f'bun add -g "{package}' not in body
            assert f"bun add -g {package}" not in body
            assert f"npm install -g {package}" not in body


def test_harness_delegation_wires_exact_module_commands() -> None:
    common = file("scripts/lib/common.sh")
    # Removed inline installers are gone.
    assert "install_ai_cli_bundle" not in common
    assert "install_antigravity_artifact" not in common
    assert "ai-cli-runtime-v1" not in common
    # Delegation helpers with the exact module commands are present.
    assert "rldyour::install_selected_harnesses" in common
    assert 'python3 "$module/$entry" install-cli --target "$target"' in common
    assert 'python3 "$module/$entry" apply --setup "$setup" --target "$target"' in common
    assert 'python3 "$module/$entry" install-builder --target "$target"' in common
    # Codex module entrypoint and safe-by-default setup.
    assert 'entry="cli-tools/nddev_codex.py"' in common
    assert 'setup="safe"' in common
    assert "RLDYOUR_CODEX_FULL_AUTO" in common
    # ADR 0006: the zcode delegation is removed outright rather than softened into
    # a warn-and-continue step, which would be exactly the best-effort fallback
    # this repository forbids. No zcode installer may come back here.
    assert "rldyour::install_zcode_harness" not in common
    assert "RLDYOUR_ZCODE_MODULE" not in common
    # The ZCode plan/apply lifecycle strings are what must be gone; `nddev-builder`
    # itself stays, because the codex module installs that marketplace too.
    assert 'bash "$module/$entry" bootstrap "$flag"' not in common
    assert 'bash "$module/$entry" install --setup nddev-builder "$flag"' not in common
    # codex must be reachable: the module publishes its CLI only under its own
    # target, so the managed PATH has to include that target's bin directory.
    assert '"${RLDYOUR_CODEX_HOME:-$HOME/.codex}/bin"' in common
    # Unset module path self-materializes the pinned public module (additive).
    assert "self-materializing the pinned codex module" in common
    assert "rldyour::_materialize_harness_module" in common
    assert "rldyour::_ensure_pinned_git_checkout" in common


def test_linux_cdp_service_carries_no_sandbox_and_macos_does_not() -> None:
    """Ubuntu 23.10+ restricts unprivileged user namespaces through AppArmor, so the
    headless Chromium zygote finds no usable sandbox and aborts with status 6/ABRT.
    Observed on 26.04: the service restarted seven times and the mandatory health
    gate failed, which correctly aborted the apply. The flag is what lets the
    managed service start at all there.

    macOS has no such restriction and keeps its sandbox, so the flag must NOT
    appear on that platform - and the provenance validators compare the argument
    tail exactly, so a shared list would break one platform or the other."""
    common = file("scripts/lib/common.sh")
    unit = next(
        line for line in common.splitlines()
        if line.startswith('ExecStart="${service_binary}"')
    )
    assert unit.endswith("--no-sandbox"), unit
    # Both provenance validators must expect it, and only for linux.
    assert common.count('if fingerprint == "linux":\n    expected_tail.append("--no-sandbox")') == 2
    # The macOS plist argument list must stay sandboxed.
    plist = common[common.index("<string>--fingerprint-platform=${fp}</string>") - 900 :]
    plist = plist[: plist.index("</array>")] if "</array>" in plist else plist
    assert "--no-sandbox" not in plist, "macOS launchd arguments must keep the sandbox"


def test_harness_layer_runs_after_the_layers_it_used_to_strand() -> None:
    """The harness layer delegates to a module whose fail-closed guards depend on
    local state this repository does not own: a stale builder profile under the
    harness target, or a checkout whose modes came from the caller's umask. Under
    `set -euo pipefail` an abort there stranded every layer behind it - the
    language servers, compiled hosts, pinned scanners, and browser stack - which
    is how a desktop ended up missing 24 of the 46 commands verify.sh required at
    the time. The failure must stay fatal; it must not stay first."""
    for installer in ("scripts/ubuntu/install.sh", "scripts/macos/install.sh"):
        body = file(installer)
        harness = body.index('[ "$SKIP_AI" -eq 1 ] || install_ai_runtimes')
        for later in ("rldyour::install_browser_providers",):
            assert body.index(later) < harness, f"{installer}: {later} must run before the harness"
        # Still fatal: no `|| true`, no warn-and-continue wrapper.
        line = next(l for l in body.splitlines() if "install_ai_runtimes" in l and "SKIP_AI" in l)
        assert "||" not in line.split("||", 1)[1].replace(" install_ai_runtimes", "", 1), line
        assert body.index("verify_apply", harness) > harness, f"{installer}: verify must follow the harness"


def test_materialized_harness_checkouts_are_permission_normalized() -> None:
    """`git clone` applies the caller's umask, and nddev-codex-app refuses a
    group- or world-writable builder source tree. Under `umask 002` the clone
    landed with 252 group-writable paths and install-builder failed closed after
    the checkout helper had already reported success. Both the fresh and the
    fast path must normalize, or a host that already has a clean pinned checkout
    stays broken forever - the fast path is the only one it takes again."""
    common = file("scripts/lib/common.sh")
    helper = "rldyour::_harness_checkout_permissions"
    assert f"{helper}() {{" in common
    checkout = common.index("rldyour::_ensure_pinned_git_checkout() {")
    body = common[checkout : common.index(f"\n{helper}() {{")]
    assert body.count(helper) == 2, "both the fast path and the clone path must normalize"
    # Reuses the shared helper rather than a third permission implementation.
    assert "rldyour::_managed_tree_permissions normalize" in common[common.index(f"{helper}() {{") :]


def test_desktop_manifests_exclude_project_runtime_and_docker() -> None:
    macos = parse_array(file("scripts/macos/install.sh"), "BREW_SOURCE_PACKAGES")
    gui_casks = parse_array(file("scripts/macos/install.sh"), "GUI_CASKS")
    ubuntu = parse_array(file("scripts/ubuntu/install.sh"), "APT_SOURCE_PACKAGES")
    # ADR 0005 admits Go and Rust as desktop language-server hosts, on the same
    # footing as Node, Python, and Homebrew's LLVM: they exist so gopls and
    # rust-analyzer can resolve the estate's Go and Rust sources. Everything
    # that provisions a container runtime, a general project build system, or a
    # second toolchain manager stays forbidden.
    forbidden_macos = {
        "docker",
        "docker-desktop",
        "rustup",
        "cmake",
        "openjdk",
        "mise",
        "deno",
        "cargo-nextest",
    }
    forbidden_ubuntu = {
        "docker.io",
        "docker-ce",
        # Distribution Go/Rust/Dart stay banned: the managed hosts are installed
        # from tracked SHA-256 artifacts into owned versioned directories, never
        # apt. ADR 0006 admits the Dart SDK, not the `dart` apt package.
        "golang-go",
        "rustc",
        "cargo",
        "dart",
        "cmake",
        "default-jdk",
        "r-base",
    }
    assert macos.isdisjoint(forbidden_macos)
    assert ubuntu.isdisjoint(forbidden_ubuntu)
    # A direct-entry ban is not enough on Homebrew: a formula's dependencies are
    # installed too. jdtls (-> openjdk) and kotlin-language-server (-> openjdk@21)
    # each pulled the JDK this manifest forbids, so the ban was satisfied on
    # paper and defeated in practice. Keep the known offenders out by name; a new
    # JVM-backed formula must be checked against `brew info --json` before it is
    # added.
    jvm_backed_formulae = {"jdtls", "kotlin-language-server", "ktlint", "google-java-format"}
    assert macos.isdisjoint(jvm_backed_formulae)
    assert "llvm" in macos  # Homebrew's supported clangd distribution only.
    # The language-server hosts admitted by ADR 0005 and ADR 0006, and their
    # servers. `dart-sdk` is Homebrew's SDK formula; it carries both the analysis
    # server and the `dart mcp-server` transport the marketplace declares.
    assert {"go", "gopls", "rust", "rust-analyzer", "dart-sdk"}.issubset(macos)
    assert "docker-language-server" in macos
    assert {"chatgpt", "codex-app"}.issubset(gui_casks)
    assert any(
        entry.startswith("dockerfile-language-server-nodejs@")
        for entry in parse_array(file("scripts/ubuntu/install.sh"), "BUN_LSP_PACKAGES")
    )
    cloak_runtime = parse_array(
        file("scripts/ubuntu/install.sh"), "APT_CLOAK_RUNTIME_PACKAGES"
    )
    for dependency in ("libnss3", "libgbm1", "libgtk-3-0t64", "fonts-liberation"):
        assert dependency in cloak_runtime


def test_server_module_owns_docker_and_safe_hardening() -> None:
    server = file("scripts/ubuntu/server.sh")
    for package in (
        "docker-ce",
        "docker-ce-cli",
        "containerd.io",
        "docker-buildx-plugin",
        "docker-compose-plugin",
    ):
        assert package in server
    assert "24.04" in server and "26.04" in server
    assert "docker group is intentionally unchanged" in server
    assert "sshd -t" in server
    assert "--enable-ufw" in server and "--harden-ssh" in server
    assert "sysctl -w" not in server
    assert "/etc/sysctl.d" not in server
    assert "/etc/security/limits" not in server
    assert "docker_rootless_preflight" in server
    assert "existing rootful Docker/containerd state will be preserved" in server
    assert "rm -f /var/run/docker.sock" not in server
    assert "/etc/apt/keyrings/rldyour-docker.asc" in server
    assert "/etc/apt/sources.list.d/rldyour-docker.sources" in server
    assert "exact ownership is recorded in a sidecar" in server
    assert "RLDYOUR_SERVER_DOCKER_GPG_FINGERPRINT" not in server
    assert "rollback_ufw" in server
    assert 'chown root:root -- "$destination"' in server


def test_browser_stack_is_mandatory_and_fixed_to_cloak() -> None:
    common = file("scripts/lib/common.sh")
    bootstrap = file("scripts/bootstrap.sh")
    contract = json.loads(file("config/rldyour-contract.json"))["browser_automation"]
    assert contract == {
        "required": True,
        "provider": "cloakbrowser",
        "cloakbrowser": "0.4.12",
        "cdp_endpoint": "http://127.0.0.1:9222",
        "fallback_allowed": False,
        "chrome_devtools_mcp": "1.6.0",
        "playwright_cli": "0.1.17",
        "active_providers": ["playwright-cli", "chrome-devtools-mcp"],
        "webwright_status": "retired-fail-closed",
        "webwright_enabled": False,
        "disabled_wrapper": "webwright",
    }
    assert "RLDYOUR_BROWSER_REQUIRED=1" in bootstrap
    assert "--skip-browser is unsupported" in bootstrap
    assert 'local pin="0.4.12"' in common
    assert "127.0.0.1:9222" in common
    assert "alternate CDP endpoint rejected" in common
    provider_manifest = json.loads(file("templates/browser/provider/package.json"))
    assert provider_manifest["dependencies"] == {
        "@playwright/cli": "0.1.17",
        "chrome-devtools-mcp": "1.6.0",
    }
    assert '"cdpEndpoint": "http://127.0.0.1:9222"' in file(
        "templates/browser/playwright-cli.json"
    )
    assert "microsoft/Webwright" not in common
    assert "webwright-uv.lock" not in common
    assert not (ROOT / "templates/browser/webwright-uv.lock").exists()
    assert not (ROOT / "templates/browser/webwright-local-cdp.yaml").exists()
    assert "--frozen-lockfile" in common
    provider_lock = file("templates/browser/provider/bun.lock")
    assert '"chrome-devtools-mcp": ["chrome-devtools-mcp@1.6.0"' in provider_lock
    assert '"@playwright/cli": ["@playwright/cli@0.1.17"' in provider_lock
    cloak_lock = file("templates/browser/cloakbrowser-uv.lock")
    assert 'name = "cloakbrowser"' in cloak_lock
    assert 'version = "0.4.12"' in cloak_lock
    assert (
        "0415acff4aa5f49c18bc9cbd6a65ae806591dfd71ddf5d862238c61cd8471142" in cloak_lock
    )


def test_browser_fail_closed_regressions_are_guarded() -> None:
    common = file("scripts/lib/common.sh")
    for forbidden in (
        "CLOAKBROWSER_BINARY_PATH",
        "CLOAKBROWSER_DOWNLOAD_URL",
        "CLOAKBROWSER_SKIP_CHECKSUM",
        "CLOAKBROWSER_VERSION",
        "CLOAKBROWSER_WIDEVINE_CDM",
    ):
        assert forbidden in common
    assert "install|install-browser|attach)" in common
    assert "run-code|--filename|--filename=*)" in common
    assert "'--' cannot bypass the mandatory CDP and privacy flags" in common
    assert "'--' cannot bypass the mandatory CDP configuration" in common
    assert "--endpoint|--endpoint=*" in common
    assert "--no-usage-statistics --no-performance-crux" in common
    assert "CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS=1" in common
    assert "NO_UPDATE_NOTIFIER=1" in common
    assert "PWTEST_DAEMON_SESSION_DIR" in common
    assert "webwright.run.cli" not in common
    assert "retired by the fail-closed browser policy" in common
    assert "exit 78" in common
    assert "MainPID" in common
    assert "fixed CDP listener is not owned by the managed service PID" in common
    assert "service executable is not the verified CloakBrowser binary" in common
    assert "browser provider executable smoke check failed" in common
    assert "_playwright_config_owner_valid" in common
    assert 'chmod "$mode" "$dest"' in common


def test_browser_trust_override_propagates_to_public_entrypoint() -> None:
    result = subprocess.run(
        [
            "bash",
            "scripts/bootstrap.sh",
            "--platform",
            "ubuntu",
            "--profile",
            "desktop",
            "--no-gui",
            "--plan",
            "--skip-system",
            "--skip-ai",
            "--skip-lsps",
            "--skip-checks",
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        env={**os.environ, "CLOAKBROWSER_BINARY_PATH": "/tmp/unmanaged-browser"},
    )
    assert result.returncode != 0
    assert "forbidden by the signed CloakBrowser trust policy" in result.stdout


def test_browser_managed_file_repairs_mode_and_rejects_marker_substrings(
    tmp_path: Path,
) -> None:
    common_path = ROOT / "scripts/lib/common.sh"
    marker = "# Managed by macos-ubuntu-bootstrap: browser-stack-v1"
    managed = tmp_path / "managed"
    managed_content = f"{marker}\npayload\n"
    managed.write_text(managed_content, encoding="utf-8")
    managed.chmod(0o600)
    script = r"""
source "$1"
export RLDYOUR_DRY_RUN=0
printf '%s' "$CONTENT" | rldyour::_install_managed_browser_file "$2" "$3" 0755
"""
    result = subprocess.run(
        ["bash", "-c", script, "_", str(common_path), str(managed), marker],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "CONTENT": managed_content},
    )
    assert result.returncode == 0, result.stderr
    assert managed.stat().st_mode & 0o777 == 0o755

    unmanaged = tmp_path / "unmanaged"
    original = f"prefix {marker} suffix\nowner data\n"
    unmanaged.write_text(original, encoding="utf-8")
    result = subprocess.run(
        ["bash", "-c", script, "_", str(common_path), str(unmanaged), marker],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "CONTENT": managed_content},
    )
    assert result.returncode != 0
    assert unmanaged.read_text(encoding="utf-8") == original



def test_browser_commands_are_required_in_verifiers() -> None:
    for platform in ("macos", "ubuntu"):
        verify = file(f"scripts/{platform}/verify.sh")
        required = parse_array(verify, "required_cmds")
        for command in (
            "cloak-chromium",
            "cloakbrowser-cdp-health",
            "chrome-devtools-mcp",
            "playwright-cli",
        ):
            assert command in required
        assert "webwright" not in required
        assert "verify-browser-runtime.sh" in verify
    ubuntu_verify = file("scripts/ubuntu/verify.sh")
    assert "tool_host_provenance" in ubuntu_verify
    assert "ubuntu-runtime-v1" in ubuntu_verify
    assert "managed_link" in ubuntu_verify


def test_macos_runtime_pillars_have_version_floors() -> None:
    # macOS provisions these via mutable Homebrew, so it cannot carry an exact
    # receipt like the Ubuntu standalone path. It must at least fail closed on
    # gross drift with a conservative version floor, not a silent presence check.
    verify = file("scripts/macos/verify.sh")
    for tool in ("uv", "bun", "starship", "atuin", "carapace"):
        assert re.search(
            rf"require_cmd_min_version {tool} ", verify
        ), f"macOS verify must floor-check {tool}"


def test_python_source_tools_are_version_pinned() -> None:
    # uv-managed source tools must carry an exact `==version` pin so two devices
    # bootstrapped at different times resolve identical releases (RVR-P2-003).
    tools = parse_array(file("scripts/ubuntu/install.sh"), "PYTHON_SOURCE_TOOLS")
    assert tools, "PYTHON_SOURCE_TOOLS must be non-empty"
    for entry in tools:
        assert "==" in entry, f"uv source tool must be exact-version pinned: {entry}"


def test_bun_lsps_are_version_pinned() -> None:
    # Every bun-installed language server / source tool must carry an exact
    # `@<version>` on both platforms (no floating latest) (RVR-P2-003).
    for platform in ("ubuntu", "macos"):
        pkgs = parse_array(file(f"scripts/{platform}/install.sh"), "BUN_LSP_PACKAGES")
        assert pkgs, f"{platform} BUN_LSP_PACKAGES must be non-empty"
        for entry in pkgs:
            assert re.search(
                r"@\d+\.\d+", entry
            ), f"{platform} bun tool must be exact-version pinned: {entry}"
    # The two corrected package identities must not regress to the wrong/absent
    # packages: bare `biome` (a squatter) and `@ansible/language-server` (absent).
    ubuntu = parse_array(file("scripts/ubuntu/install.sh"), "BUN_LSP_PACKAGES")
    assert any(e.startswith("@biomejs/biome@") for e in ubuntu)
    assert not any(e == "biome" or e.startswith("biome@") for e in ubuntu)
    assert any(e.startswith("@ansible/ansible-language-server@") for e in ubuntu)
    assert not any(e == "@ansible/language-server" or e.startswith("@ansible/language-server@") for e in ubuntu)


def test_remote_code_is_never_piped_directly_to_shell() -> None:
    for path in (ROOT / "scripts").rglob("*.sh"):
        body = path.read_text(encoding="utf-8")
        assert not re.search(r"curl[^\n|]*\|\s*(?:ba)?sh", body), path


def test_remote_installers_have_tracked_integrity_roots() -> None:
    macos = file("scripts/macos/install.sh")
    ubuntu = file("scripts/ubuntu/install.sh")
    common = file("scripts/lib/common.sh")
    assert "HOMEBREW_PKG_VERSION=" in macos
    assert "HOMEBREW_PKG_SHA256=" in macos
    assert "pkgutil --check-signature" in macos
    assert "spctl --assess --type install" in macos
    for body in (macos, ubuntu):
        # Removed harness installers stay gone; the streamed Antigravity installer
        # was always forbidden.
        assert "install_antigravity_artifact" not in body
        assert "antigravity.google/cli/install.sh" not in body
    # AGY_CLI_DISABLE_AUTO_UPDATE related to Antigravity and is fully removed;
    # DISABLE_AUTOUPDATER/DISABLE_UPDATES stay to keep the codex harness locked.
    assert "AGY_CLI_DISABLE_AUTO_UPDATE" not in common
    assert "AGY_CLI_DISABLE_AUTO_UPDATE" not in file("templates/terminal/zshenv")
    assert "DISABLE_AUTOUPDATER=1" in file("templates/terminal/zshenv")
    assert "DISABLE_UPDATES=1" in file("templates/terminal/zshenv")
    assert "download_verified_file" in common
    assert "astral.sh/uv/install.sh" not in ubuntu
    assert "bun.sh/install" not in ubuntu
    supply = json.loads(file("config/rldyour-contract.json"))["supply_chain"]
    assert "ai_cli_lock" not in supply
    assert not any("antigravity" in key for key in supply)
    for value in supply.values():
        if isinstance(value, bool):
            continue
        assert str(value) in macos + ubuntu + common or str(value).startswith(
            "templates/"
        )


def test_existing_homebrew_packages_are_never_implicitly_upgraded() -> None:
    macos = file("scripts/macos/install.sh")
    assert "brew upgrade" not in macos
    assert "brew outdated" not in macos
    assert "preserving installed Homebrew formula" in macos
    assert "preserving installed Homebrew cask" in macos
    assert "cask_app_path" in macos
    assert "preserving signed and notarized unmanaged cask destination" in macos
    assert 'codesign --verify --deep --strict "$app_path"' in macos
    assert 'spctl --assess --type execute "$app_path"' in macos
    ensure_cask = re.search(
        r"^ensure_cask\(\) \{(.*?)(?=^\w[^\n]*\(\) \{)",
        macos,
        re.MULTILINE | re.DOTALL,
    )
    assert ensure_cask is not None
    body = ensure_cask.group(1)
    assert body.index('brew list --cask "$cask"') < body.index(
        'brew install --cask "$cask"'
    )
    assert body.index('verify_existing_cask_app "$cask" "$app_path"') < body.index(
        'brew install --cask "$cask"'
    )


def test_versioned_native_artifacts_publish_on_the_destination_filesystem() -> None:
    common = file("scripts/lib/common.sh")
    ubuntu = file("scripts/ubuntu/install.sh")
    assert ".node-${NODE_VERSION}.tmp.XXXXXX" in ubuntu
    assert ".uv-${UV_VERSION}.tmp.XXXXXX" in ubuntu
    assert ".bun-${BUN_VERSION}.tmp.XXXXXX" in ubuntu
    assert 'mv "$stage" "$destination"' in ubuntu
    assert "ubuntu-runtime-v1" in ubuntu
    assert "validate_runtime_receipt" in ubuntu
    assert "preflight_managed_link" in ubuntu
    for function_name in ("ensure_node", "ensure_uv", "ensure_bun"):
        match = re.search(
            rf"^{function_name}\(\) \{{(.*?)(?=^\w[^\n]*\(\) \{{)",
            ubuntu,
            re.MULTILINE | re.DOTALL,
        )
        assert match is not None
        assert "command -v" not in match.group(
            1
        ), f"{function_name} must not trust an external PATH version"


def test_auth_handoff_contains_all_manual_boundaries() -> None:
    handoff = file("scripts/auth-handoff.sh")
    for marker in (
        "gh auth login",
        "codex login --device-auth",
        "open ChatGPT.app",
        "open Codex.app",
        "zcode.z.ai",
        "cloakbrowser-cdp-health",
        "Settings → Secrets and variables → Actions",
    ):
        assert marker in handoff
    # Removed harnesses must not linger in the handoff steps.
    for absent in ("claude auth login", "opencode auth login", "agy"):
        assert absent not in handoff
    assert "never reads" in handoff


def test_shell_dropins_preserve_user_files_and_are_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    zshenv = home / ".zshenv"
    zprofile = home / ".zprofile"
    zshenv.write_text("# owner zshenv\nexport OWNER_VALUE=kept\n", encoding="utf-8")
    zprofile.write_text("# owner zprofile\n", encoding="utf-8")
    zshenv.chmod(0o600)
    script = r"""
source "$1"
export RLDYOUR_DRY_RUN=0
rldyour::install_terminal_configs "$2"
rldyour::install_terminal_configs "$2"
"""
    result = subprocess.run(
        [
            "bash",
            "-c",
            script,
            "_",
            str(ROOT / "scripts/lib/common.sh"),
            str(ROOT / "templates/terminal"),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert zshenv.stat().st_mode & 0o777 == 0o600
    assert zshenv.read_text(encoding="utf-8").startswith(
        "# owner zshenv\nexport OWNER_VALUE=kept\n"
    )
    assert (
        zshenv.read_text(encoding="utf-8").count(
            'source "$HOME/.config/rldyour/zshenv"'
        )
        == 1
    )
    assert (
        zprofile.read_text(encoding="utf-8").count(
            'source "$HOME/.config/rldyour/zprofile"'
        )
        == 1
    )
    managed = home / ".config/rldyour/zshenv"
    assert managed.read_text(encoding="utf-8").startswith(
        "# Managed by macos-ubuntu-bootstrap: terminal-zshenv-v1"
    )
    backups = list((home / ".local/share/rldyour/backups/shell").rglob(".zshenv"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == (
        "# owner zshenv\nexport OWNER_VALUE=kept\n"
    )


def test_ssh_activation_and_reload_preserve_existing_provider(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "systemctl.log"
    systemctl = fake_bin / "systemctl"
    systemctl.write_text(
        r"""#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  is-active)
    [ "${ACTIVE_PROVIDER:-}" = "$3" ] ||
      { [ -f "$SYSTEMCTL_STATE" ] && grep -Fxq "$3" "$SYSTEMCTL_STATE"; }
    ;;
  is-enabled) [ "${ENABLED_PROVIDER:-}" = "$3" ] ;;
  list-unit-files)
    case "${AVAILABLE_PROVIDER:-ssh.service}" in
      ssh.service) printf 'ssh.service enabled\n' ;;
      ssh.socket) printf 'ssh.socket enabled\n' ;;
    esac
    ;;
  enable)
    printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
    printf '%s\n' "${@: -1}" > "$SYSTEMCTL_STATE"
    ;;
  reload) printf '%s\n' "$*" >> "$SYSTEMCTL_LOG" ;;
  *) exit 2 ;;
esac
""",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    script = r"""
source "$1"
export RLDYOUR_DRY_RUN=0
rldyour::ubuntu_server::as_root() { "$@"; }
rldyour::ubuntu_server::ensure_ssh_activation
rldyour::ubuntu_server::reload_ssh_authentication
"""
    base_env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "SYSTEMCTL_LOG": str(log),
        "SYSTEMCTL_STATE": str(tmp_path / "systemctl.state"),
    }
    for provider in ("ssh.service", "ssh.socket"):
        log.write_text("", encoding="utf-8")
        result = subprocess.run(
            ["bash", "-c", script, "_", str(ROOT / "scripts/ubuntu/server.sh")],
            check=False,
            capture_output=True,
            text=True,
            env={**base_env, "ACTIVE_PROVIDER": provider},
        )
        assert result.returncode == 0, result.stderr + result.stdout
        calls = log.read_text(encoding="utf-8")
        if provider == "ssh.service":
            assert calls == "reload ssh.service\n"
        else:
            assert calls == ""

    log.write_text("", encoding="utf-8")
    result = subprocess.run(
        ["bash", "-c", script, "_", str(ROOT / "scripts/ubuntu/server.sh")],
        check=False,
        capture_output=True,
        text=True,
        env={**base_env, "ENABLED_PROVIDER": "ssh.socket"},
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert log.read_text(encoding="utf-8") == "enable --now ssh.socket\n"


def test_ssh_port_detection_uses_privileged_read_only_probe() -> None:
    script = r"""
source "$1"
systemctl() { return 1; }
sshd() { return 0; }
rldyour::ubuntu_server::probe_as_root() {
  [ "$1 $2" = "sshd -T" ] || exit 9
  printf 'port 2202\n'
}
rldyour::ubuntu_server::detect_ssh_port
"""
    result = subprocess.run(
        ["bash", "-c", script, "_", str(ROOT / "scripts/ubuntu/server.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip() == "2202"


def test_browser_owned_templates_and_files_are_preserved_fail_closed() -> None:
    common = file("scripts/lib/common.sh")
    assert "unmanaged browser file differs; preserved" in common
    assert "browser provider home exists without a management marker" in common
    assert "stock Chromium" in common


def test_no_gui_mode_is_distinct_from_server_role() -> None:
    bootstrap = file("scripts/bootstrap.sh")
    macos = file("scripts/macos/install.sh")
    assert "export RLDYOUR_GUI_ENABLED=1" in bootstrap
    assert "export RLDYOUR_GUI_ENABLED=0" in bootstrap
    assert 'RLDYOUR_LOCAL_EXECUTION_POLICY="source-lsp-only"' in bootstrap
    assert 'RLDYOUR_LOCAL_EXECUTION_POLICY="container-execution-only"' in bootstrap
    install_gui = re.search(
        r"^install_gui_apps\(\) \{(.*?)(?=^\w[^\n]*\(\) \{)",
        macos,
        re.MULTILINE | re.DOTALL,
    )
    assert install_gui is not None
    body = install_gui.group(1)
    assert body.index('if [ "$GUI_ENABLED" -ne 1 ]; then') < body.index(
        'for cask in "${GUI_CASKS[@]}"'
    )
    assert "codex-app" in parse_array(macos, "GUI_CASKS")
    assert "for app in Ghostty cmux ChatGPT Codex Claude" in file(
        "scripts/macos/verify.sh"
    )
    assert 'for agent in codex; do' in macos
    assert 'cmux hooks "$agent" install --yes' in macos
    assert "cmux hooks setup" not in macos
    assert "opencode" not in macos
    assert "antigravity" not in macos


def test_reusable_ci_is_pinned_to_current_ci_workflows_release() -> None:
    # ci-workflows 0.13.3. Advancing this constant is the deliberate act that
    # repins the whole repository: the assertion below rejects a workflow left
    # behind, which is how thirteen callers were found still on 0.12.0.
    expected = "7f69c724923d06b2c2057c5a6ad341c37f1a8995"
    found = 0
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        body = workflow.read_text(encoding="utf-8")
        for sha in re.findall(
            r"NDDev-it-com/ci-workflows/[^@\s]+@([0-9a-f]{40})", body
        ):
            found += 1
            assert sha == expected, f"{workflow.name} has stale central CI pin {sha}"
    assert found >= 8


def test_hosted_workflows_provision_local_validator_prerequisites() -> None:
    for workflow in (
        ".github/workflows/ci.yml",
        ".github/workflows/validate.yml",
        ".github/workflows/release.yml",
    ):
        body = file(workflow)
        assert "ripgrep" in body, f"{workflow} must provision rg explicitly"
    for workflow in (".github/workflows/pytest.yml", ".github/workflows/release.yml"):
        body = file(workflow)
        assert (
            "zsh" in body
        ), f"{workflow} must provision zsh for terminal portability tests"


def test_raven_actionlint_uses_no_unsupported_args_input() -> None:
    found = 0
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        lines = workflow.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "uses: raven-actions/actionlint@" not in line:
                continue
            found += 1
            use_indent = len(line) - len(line.lstrip())
            nested_lines = []
            for nested in lines[index + 1 :]:
                if nested.strip() and len(nested) - len(nested.lstrip()) < use_indent:
                    break
                nested_lines.append(nested)
            assert not any(
                re.match(r"^\s*args\s*:", nested) for nested in nested_lines
            ), f"{workflow.name} passes unsupported args to raven actionlint"
    assert found > 0


def test_dependency_check_enforces_one_owner_per_harness_delegation() -> None:
    workflow = file(".github/workflows/dependency-check.yml")
    assert "one-owner-per-harness delegation" in workflow
    assert "rldyour::install_selected_harnesses" in workflow
    assert "RLDYOUR_CODEX_MODULE" in workflow
    # ADR 0006: the workflow now gates on zcode staying OUT of bootstrap.
    assert "zcode is delegated out of bootstrap" in workflow
    assert "the frozen AI-CLI bundle template must be removed" in workflow
    assert "streamed installer is forbidden" in workflow


def test_release_keeps_numeric_tag_push_path() -> None:
    release = file(".github/workflows/release.yml")
    assert 'tags:\n      - "[0-9]+.[0-9]+.[0-9]+"' in release
    assert "RELEASE_REF_NAME: ${{ github.ref_name }}" in release
    assert "RELEASE_REF_TYPE: ${{ github.ref_type }}" in release
    assert '[ "$RELEASE_REF_TYPE" = "tag" ]' in release


def test_release_manual_dispatch_requires_existing_safe_exact_tag() -> None:
    release = file(".github/workflows/release.yml")
    assert "workflow_dispatch:" in release
    assert "inputs:\n      version:" in release
    assert "RELEASE_INPUT_VERSION: ${{ inputs.version }}" in release
    input_lines = [
        line.strip() for line in release.splitlines() if "${{ inputs.version }}" in line
    ]
    assert input_lines == ["RELEASE_INPUT_VERSION: ${{ inputs.version }}"]
    assert (
        "group: release-${{ github.workflow }}-${{ inputs.version || github.ref_name }}"
        in release
    )
    assert "without leading zeros" in release
    assert "manual release must dispatch the exact origin/main commit" in release
    assert "check_name=bootstrap-gate&status=completed" in release
    assert "verify-tag:\n    name: Verify exact manual release tag" in release
    assert "checks: read\n      contents: read" in release
    assert "persist-credentials: false" in release
    assert "persist-credentials: true" not in release
    assert "Require existing exact release tag" in release
    assert "root automation creates tags" in release
    assert 'git tag "$RELEASE_VERSION"' not in release
    assert "git push origin" not in release
    assert 'git rev-parse --verify "${tag_ref}^{commit}"' in release
    assert "existing tag '$RELEASE_VERSION' points to a different commit" in release
    assert "needs: [resolve, verify-tag]" in release
    assert "needs.verify-tag.result == 'skipped'" in release
    assert "--force" not in release
    assert "gh release create" in release
    assert "--verify-tag" in release
