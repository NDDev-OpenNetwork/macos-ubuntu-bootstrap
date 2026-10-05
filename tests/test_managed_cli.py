from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_SPEC = importlib.util.spec_from_file_location("managed_cli", ROOT / "scripts/managed_cli.py")
cli = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(cli)


def fixture(tmp_path: Path, monkeypatch, *, unsafe: str | None = None):
    archive = tmp_path / "fixture.tgz"
    with tarfile.open(archive, "w:gz") as bundle:
        for name, value, mode in [
            ("package/bin/check-cli", b"#!/bin/sh\nprintf 'check-cli 1.2.3\\n'\n", 0o755),
            ("package/lib/runtime.js", b"verified auxiliary runtime\n", 0o644),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(value)
            info.mode = mode
            bundle.addfile(info, io.BytesIO(value))
        if unsafe:
            info = tarfile.TarInfo(unsafe)
            info.size = 4
            bundle.addfile(info, io.BytesIO(b"evil"))
    artifact = {"url": "https://example.invalid/reviewed.tgz", "bytes": archive.stat().st_size,
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "member": "package/bin/check-cli"}
    spec = {"version": "1.2.3", "command": "check-cli", "shape": "gzip-tar", "artifacts": {"linux/x86_64": artifact}}
    calls = []
    def download(_artifact, destination):
        calls.append(str(destination))
        shutil.copyfile(archive, destination)
    monkeypatch.setattr(cli, "download", download)
    home = tmp_path / "home"
    home.mkdir()
    return home, spec, calls


def test_install_runs_exact_program_and_repeat_is_offline(tmp_path, monkeypatch):
    home, spec, calls = fixture(tmp_path, monkeypatch)
    first = cli.install(home, "check", spec, "linux/x86_64")
    second = cli.install(home, "check", spec, "linux/x86_64")
    assert first == second
    assert len(calls) == 1
    assert (home / ".local/bin/check-cli").resolve() == Path(first["resolved"])


def test_auxiliary_payload_tampering_fails_verify_and_repeat_apply(tmp_path, monkeypatch):
    home, spec, _ = fixture(tmp_path, monkeypatch)
    cli.install(home, "check", spec, "linux/x86_64")
    library = cli.root_for(home, "check", spec) / "package/lib/runtime.js"
    library.write_text("changed runtime")
    with pytest.raises(cli.CLIError, match="payload differs"):
        cli.verify(home, "check", spec, "linux/x86_64")
    with pytest.raises(cli.CLIError, match="payload differs"):
        cli.install(home, "check", spec, "linux/x86_64")
    assert library.read_text() == "changed runtime"


def test_integrity_refusal_preserves_existing_launcher(tmp_path, monkeypatch):
    home, spec, _ = fixture(tmp_path, monkeypatch)
    old = home / ".local/bin/check-cli"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"previous owner's program\n")
    spec["artifacts"]["linux/x86_64"]["sha256"] = "0" * 64
    with pytest.raises(cli.CLIError, match="integrity mismatch"):
        cli.install(home, "check", spec, "linux/x86_64")
    assert not old.is_symlink()
    assert old.read_bytes() == b"previous owner's program\n"
    assert not cli.root_for(home, "check", spec).exists()


@pytest.mark.parametrize("unsafe", ["../escape", "/absolute", "package/../../escape"])
def test_verified_but_unsafe_archive_is_refused(tmp_path, monkeypatch, unsafe):
    home, spec, _ = fixture(tmp_path, monkeypatch, unsafe=unsafe)
    with pytest.raises(cli.CLIError, match="unsafe archive path"):
        cli.install(home, "check", spec, "linux/x86_64")
    assert not (home / ".local/bin/check-cli").exists()
    assert not (tmp_path / "escape").exists()


def test_previous_launcher_is_preserved_byte_exact(tmp_path, monkeypatch):
    home, spec, _ = fixture(tmp_path, monkeypatch)
    old = home / ".local/bin/check-cli"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"previous owner's program\n")
    cli.install(home, "check", spec, "linux/x86_64")
    backups = list((home / ".local/share/rldyour/backups/cli").glob("*/check-cli"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"previous owner's program\n"


def test_nonfile_launcher_is_preserved(tmp_path, monkeypatch):
    home, spec, _ = fixture(tmp_path, monkeypatch)
    (home / ".local/bin/check-cli").mkdir(parents=True)
    with pytest.raises(cli.CLIError, match="non-file launcher preserved"):
        cli.install(home, "check", spec, "linux/x86_64")
    assert (home / ".local/bin/check-cli").is_dir()


def test_ubuntu_shared_user_parent_permissions_are_preserved(tmp_path, monkeypatch):
    home, spec, _ = fixture(tmp_path, monkeypatch)
    shared = home / ".local/share/rldyour"
    shared.mkdir(parents=True)
    shared.chmod(0o775)
    cli.install(home, "check", spec, "linux/x86_64")
    assert shared.stat().st_mode & 0o777 == 0o775
    root = cli.root_for(home, "check", spec)
    assert root.stat().st_mode & 0o022 == 0
    root.chmod(0o775)
    with pytest.raises(cli.CLIError, match="unsafe managed program tree"):
        cli.verify(home, "check", spec, "linux/x86_64")


def test_ubuntu_private_group_umask_cannot_make_payload_writable(tmp_path, monkeypatch):
    home, spec, _ = fixture(tmp_path, monkeypatch)
    previous = os.umask(0o002)
    try:
        cli.install(home, "check", spec, "linux/x86_64")
    finally:
        os.umask(previous)
    root = cli.root_for(home, "check", spec)
    assert all(path.stat().st_mode & 0o022 == 0 for path in root.rglob("*"))
    cli.verify(home, "check", spec, "linux/x86_64")


def test_missing_architecture_is_not_silently_substituted(tmp_path, monkeypatch):
    home, spec, calls = fixture(tmp_path, monkeypatch)
    with pytest.raises(cli.CLIError, match="no reviewed artifact"):
        cli.install(home, "check", spec, "linux/arm64")
    assert calls == []


def test_command_shadowing_is_refused(tmp_path, monkeypatch):
    home, spec, _ = fixture(tmp_path, monkeypatch)
    cli.install(home, "check", spec, "linux/x86_64")
    link = home / ".local/bin/check-cli"
    link.unlink()
    link.symlink_to("/bin/true")
    with pytest.raises(cli.CLIError, match="launcher differs"):
        cli.verify(home, "check", spec, "linux/x86_64")


def test_canonical_seven_and_godaddy_have_reviewed_artifacts_for_every_target():
    contract = json.loads((ROOT / "config/rldyour-contract.json").read_text())
    expected = {"antigravity", "claude-code", "codex", "cursor", "grok-build", "opencode", "pi"}
    assert set(contract["harnesses"]["active"]) == expected
    specs = cli.specifications(contract)
    assert set(specs) == expected | {"gddy"}
    for name, spec in specs.items():
        for platform in ("linux/x86_64", "linux/arm64", "macos/arm64"):
            artifact = cli.artifact_for(spec, platform)
            assert spec["version"] in artifact["url"]
            cli.safe_relative(artifact["member"])
        if name != "gddy":
            assert spec["source"]["setup_system"].startswith("NDDev-OpenNetwork/")
            assert contract["harnesses"]["detection"][name]["enforcement"] == "owned-prefix"


def test_macos_plan_on_linux_uses_supported_apple_silicon_and_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "platform_key", lambda: "linux/x86_64")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(sys, "argv", ["managed_cli.py", "install", "--plan", "--platform", "macos"])
    assert cli.main() == 0
    output = capsys.readouterr().out
    assert "darwin-arm" in output or "apple-darwin" in output
    assert "[plan] gddy " in output
    assert list(tmp_path.iterdir()) == []


def cursor_runtime_fixture(tmp_path, monkeypatch):
    home, spec, calls = fixture(tmp_path, monkeypatch)
    spec.update(linux_runtime_entry="package/lib/runtime.js", linux_node_major=24)
    contract = json.loads(cli.CONTRACT.read_text())["runtime_support"]
    version = contract["ubuntu_node_lts"]
    root = home / ".local/share/rldyour/node" / f"v{version}"
    (root / "bin").mkdir(parents=True)
    node = root / "bin/node"
    node.write_text("#!/bin/sh\nprintf 'check-cli 1.2.3\\n'\n")
    node.chmod(0o755)
    receipt = root / ".rldyour-runtime-receipt"
    receipt.write_text("\n".join([
        "# Managed by macos-ubuntu-bootstrap: ubuntu-runtime-v1", "runtime=node",
        f"version={version}", "archive_sha256=" + contract["ubuntu_node_sha256"]["x64"],
        "sha256_bin_node=" + cli.sha256(node),
    ]) + "\n")
    receipt.chmod(0o600)
    return home, spec, calls, node


def test_linux_cursor_launcher_uses_and_binds_verified_bootstrap_node(tmp_path, monkeypatch):
    home, spec, _, node = cursor_runtime_fixture(tmp_path, monkeypatch)
    cli.install(home, "cursor", spec, "linux/x86_64")
    binary = home / ".local/bin/check-cli"
    assert binary.resolve().name == ".bootstrap-launcher"
    result = subprocess.run([str(binary), "--version"], capture_output=True, text=True,
                            env={"PATH": os.defpath, "HOME": str(home)}, check=True)
    assert "1.2.3" in result.stdout
    node.write_text("changed Node dependency")
    with pytest.raises(cli.CLIError, match="Node dependency payload differs"):
        cli.verify(home, "cursor", spec, "linux/x86_64")


def test_cursor_runtime_does_not_fall_back_to_unverified_path_node(tmp_path, monkeypatch):
    home, spec, _, node = cursor_runtime_fixture(tmp_path, monkeypatch)
    node.unlink()
    with pytest.raises(cli.CLIError, match="Node dependency"):
        cli.install(home, "cursor", spec, "linux/x86_64")
    assert not (home / ".local/bin/check-cli").exists()


def test_macos_cursor_retains_vendor_runtime_without_linux_dependency(tmp_path, monkeypatch):
    home, spec, _ = fixture(tmp_path, monkeypatch)
    spec.update(linux_runtime_entry="package/lib/runtime.js", linux_node_major=24)
    spec["artifacts"]["macos/arm64"] = spec["artifacts"]["linux/x86_64"]
    cli.install(home, "cursor", spec, "macos/arm64")
    assert (home / ".local/bin/check-cli").resolve().name == "check-cli"


def test_partial_transport_resumes_and_checks_complete_digest(tmp_path, monkeypatch):
    value = b"verified complete program archive"
    destination = tmp_path / "download"
    artifact = {"url": "https://example.invalid/program", "bytes": len(value),
                "sha256": hashlib.sha256(value).hexdigest()}
    calls = []
    def partial_then_complete(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            destination.write_bytes(value[:7])
            raise subprocess.CalledProcessError(18, command)
        assert "--continue-at" in command
        destination.write_bytes(value)
    monkeypatch.setattr(cli.subprocess, "run", partial_then_complete)
    cli.download(artifact, destination)
    assert len(calls) == 2
    assert all("--http1.1" in call for call in calls)


def test_transport_retries_are_bounded(tmp_path, monkeypatch, capsys):
    calls = []
    def always_timeout(command, **kwargs):
        calls.append(command)
        raise subprocess.CalledProcessError(28, command)
    monkeypatch.setattr(cli.subprocess, "run", always_timeout)
    with pytest.raises(subprocess.CalledProcessError):
        cli.download({"url": "https://example.invalid/program"}, tmp_path / "download")
    assert len(calls) == 3
    assert capsys.readouterr().out.count("bounded resume") == 2
