"""Public application metadata and non-destructive installation controls."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("harness_apps", ROOT / "scripts/ubuntu/harness-apps.py")
apps = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(apps)


def test_desktop_manifest_and_cli_contract_share_eight_identities():
    data = apps.load()
    assert len(data["apps"]) == 8
    assert {name for name, spec in data["apps"].items() if spec["desktop"]} == {
        "antigravity", "claude-code", "codex", "cursor", "opencode", "devin"
    }


def test_vendor_generated_cursor_source_is_recognized_without_rewriting():
    source = apps.load()["apps"]["cursor"]["apt_source"]
    text = apps.apt_source_text(source, "amd64").replace("Architectures: amd64", "Architectures: amd64,arm64")
    assert apps.source_matches("# Vendor-generated source\n" + text, source, "amd64")
    assert not apps.source_matches(text.replace(source["uri"], "https://example.invalid"), source, "amd64")
    assert not apps.source_matches(text + "Enabled: no\n", source, "amd64")


def test_changed_source_is_preserved_before_network_or_privilege(tmp_path, monkeypatch):
    source = dict(apps.load()["apps"]["devin"]["apt_source"])
    target = tmp_path / "devin.list"
    target.write_text("# operator-controlled\ndeb https://example.invalid stable main\n")
    source.update(source_file=str(target), keyring=str(tmp_path / "key.gpg"))
    monkeypatch.setattr(apps, "download_verified", lambda *args: pytest.fail("Must not download"))
    monkeypatch.setattr(apps.subprocess, "run", lambda *args, **kwargs: pytest.fail("Must not mutate"))
    with pytest.raises(ValueError, match="Modified APT source preserved"):
        apps.ensure_apt_source({"apt_source": source}, "amd64")
    assert "operator-controlled" in target.read_text()


def test_unsupported_architecture_refuses_before_apt(monkeypatch):
    monkeypatch.setattr(apps, "architecture", lambda: "arm64")
    monkeypatch.setattr(apps.subprocess, "run", lambda *args, **kwargs: pytest.fail("Must not mutate"))
    with pytest.raises(ValueError, match="amd64 only"):
        apps.install(apps.load())


def test_plan_writes_nothing_and_never_invokes_installed_apps(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(apps.subprocess, "run", lambda *args, **kwargs: pytest.fail("Plan must not execute"))
    monkeypatch.setattr(apps, "install", lambda *args: pytest.fail("Plan must not install"))
    monkeypatch.setattr("sys.argv", ["harness-apps.py", "plan"])
    monkeypatch.chdir(tmp_path)
    assert apps.main() == 0
    assert len(json.loads(capsys.readouterr().out)["apps"]) == 8
    assert list(tmp_path.iterdir()) == []


def test_verified_updates_refuse_user_policy_before_any_package_command(monkeypatch):
    monkeypatch.setattr(apps.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(apps.subprocess, "run", lambda *args, **kwargs: pytest.fail("Must not mutate"))
    with pytest.raises(ValueError, match="root-owned"):
        apps.update_verified(apps.load())


def test_verified_updates_never_install_absent_packages_or_touch_native_owners(monkeypatch):
    monkeypatch.setattr(apps.os, "geteuid", lambda: 0)
    monkeypatch.setattr(apps, "architecture", lambda: "amd64")
    monkeypatch.setattr(apps, "installed_package", lambda name: False)
    monkeypatch.setattr(apps, "install_deb_package", lambda *args: pytest.fail("Must not install"))
    data = {"apps": {"desktop": {"desktop": True, "install": "apt-package", "package": "fixture"},
                     "native": {"desktop": True, "install": "apt"}, "pi": {"desktop": False}}}
    result = apps.update_verified(data)
    assert [item["state"] for item in result["components"]] == ["not-installed", "native-owner", "cli-only"]
    assert not any(item["changed"] for item in result["components"])


def test_verified_updates_do_not_downgrade_or_back_up_newer_packages(monkeypatch):
    monkeypatch.setattr(apps.os, "geteuid", lambda: 0)
    monkeypatch.setattr(apps, "architecture", lambda: "amd64")
    monkeypatch.setattr(apps, "installed_package", lambda name: True)
    monkeypatch.setattr(apps.subprocess, "check_output", lambda *args, **kwargs: "99.0")
    monkeypatch.setattr(apps.subprocess, "run", lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1))
    monkeypatch.setattr(apps, "install_deb_package", lambda *args: pytest.fail("Must not downgrade"))
    data = {"apps": {"fixture": {"desktop": True, "install": "apt-package", "package": "fixture", "version": "1.0"}}}
    result = apps.update_verified(data)
    assert result["components"][0]["state"] == "current-or-newer"
    assert result["components"][0]["changed"] is False
