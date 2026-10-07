"""Public application metadata and non-destructive installation controls."""
from __future__ import annotations

import importlib.util
import json
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
