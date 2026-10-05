from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
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
