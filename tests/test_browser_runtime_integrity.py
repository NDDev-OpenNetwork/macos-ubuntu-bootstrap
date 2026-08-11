from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/browser_runtime_integrity.py"
SPEC = importlib.util.spec_from_file_location("browser_runtime_integrity", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
integrity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(integrity)


def write_receipt(path: Path, state: dict[str, object]) -> None:
    path.write_bytes(integrity.canonical_bytes(integrity.payload_with_integrity(state)))
    path.chmod(0o600)


def minimal_state() -> dict[str, object]:
    return {
        "schema": integrity.SCHEMA,
        "owner": integrity.OWNER,
        "bootstrap_version": integrity.BOOTSTRAP_VERSION,
        "home": str(Path.home()),
    }


def test_policy_contract_exposes_only_two_active_providers() -> None:
    integrity.validate_contract()
    contract = json.loads(
        (ROOT / "config/rldyour-contract.json").read_text(encoding="utf-8")
    )
    browser = contract["browser_automation"]
    assert browser["linux_service_dbus_address"] == "disabled:"
    assert browser["active_providers"] == ["playwright-cli", "chrome-devtools-mcp"]
    assert browser["webwright_status"] == "retired-fail-closed"
    assert browser["webwright_enabled"] is False
    assert browser["disabled_wrapper"] == "webwright"
    assert integrity.ACTIVE_PROVIDERS == ["playwright-cli", "chrome-devtools-mcp"]
    assert b"exit 78\n" in integrity.DISABLED_WEBWRIGHT
    assert b"NOT_PROVEN" in integrity.DISABLED_WEBWRIGHT


def test_cloak_runtime_identity_preserves_repository_logical_names(
    tmp_path: Path,
) -> None:
    platform_label = "Darwin-arm64"
    # Mirrors cloak_runtime_identity(): these are Git-tracked sources, whose
    # group-write bit is decided by the umask at clone time, so the private-mode
    # precondition does not apply to them.
    expected = integrity.content_id(
        f"cloakbrowser|version={integrity.CLOAK_VERSION}|platform={platform_label}",
        [
            ROOT / "templates/browser/cloakbrowser-pyproject.toml",
            ROOT / "templates/browser/cloakbrowser-uv.lock",
        ],
        repository_sources=True,
    )
    assert integrity.cloak_runtime_identity(platform_label) == expected

    # Installed files intentionally use conventional project names. Their
    # bytes match, but those renamed paths are not the installer's logical
    # content-ID inputs.
    project = tmp_path / "pyproject.toml"
    lock = tmp_path / "uv.lock"
    project.write_bytes(
        (ROOT / "templates/browser/cloakbrowser-pyproject.toml").read_bytes()
    )
    lock.write_bytes((ROOT / "templates/browser/cloakbrowser-uv.lock").read_bytes())
    # These stand in for *installed* runtime files, so the private-mode
    # precondition does apply. The test creates them, so under a umask of 002
    # they would arrive group-writable and fail for a reason unrelated to the
    # behaviour under test.
    project.chmod(0o644)
    lock.chmod(0o644)
    assert (
        integrity.content_id(
            f"cloakbrowser|version={integrity.CLOAK_VERSION}|platform={platform_label}",
            [project, lock],
        )
        != expected
    )


def test_private_mode_is_enforced_for_installed_files_and_not_for_sources(
    tmp_path: Path,
) -> None:
    """Git records only the executable bit, so a checkout's group-write bit comes
    from the umask at clone time. Enforcing it on repository sources made the
    gate fail on a pristine tree under `umask 002` while proving nothing — anyone
    who can write those files can change their contents. Enforcing it on files
    the installer created is real tamper resistance and must stay."""
    payload = tmp_path / "artifact.txt"
    payload.write_bytes(b"managed runtime bytes\n")
    payload.chmod(0o664)

    # As an installed runtime file: group-writable is refused.
    with pytest.raises(integrity.IntegrityError, match="group/world-writable"):
        integrity.content_id("installed", [payload])

    # As a repository source: the same file is accepted, and yields the same
    # identity it would at 0644, because the mode is not part of the digest.
    group_writable_id = integrity.content_id(
        "source", [payload], repository_sources=True
    )
    payload.chmod(0o644)
    assert integrity.content_id("source", [payload], repository_sources=True) == (
        group_writable_id
    )
    # And the stricter reading still passes once the bit is gone.
    assert integrity.content_id("installed", [payload])

    # World-writable is refused for installed files regardless.
    payload.chmod(0o646)
    with pytest.raises(integrity.IntegrityError, match="group/world-writable"):
        integrity.content_id("installed", [payload])


def test_policy_hashes_treats_its_inputs_as_repository_sources() -> None:
    """policy_hashes() reads eight Git-tracked files - this script, common.sh, the
    contract, and five templates - and was the call site where the 2.2.0 flag had
    been dropped. Under `umask 002` a clone writes them 664, so the live
    verify-browser-runtime run failed with

        NOT_PROVEN: path is group/world-writable: .../browser_runtime_integrity.py

    on a pristine tree, while `umask 022` hosts and CI stayed green. Hashing is
    what pins these files; the mode says nothing about them, because anyone who can
    write a source can edit its contents. The installed-path refusal is untouched
    and must stay - see the test above."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    call = source[source.index("def policy_hashes()") : source.index("def validate_contract()")]
    assert "regular_owned(path, enforce_private_mode=False)" in call
    assert "regular_owned(path)\n" not in call, "private mode must not be re-enforced here"
    # It still hashes every input, which is the actual pin.
    assert "sha256_file(path)" in call
    # Proven live: the real repository tree passes regardless of its clone umask.
    assert set(integrity.policy_hashes()) == {
        "integrity_policy",
        "installer_policy",
        "contract",
        "cloak_project",
        "cloak_lock",
        "provider_manifest",
        "provider_lock",
        "playwright_config",
    }


def test_receipt_round_trip_rejects_payload_tampering(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    state = minimal_state()
    write_receipt(receipt, state)
    loaded = integrity.load_receipt(receipt)
    assert loaded["payload_sha256"] == integrity.sha256_bytes(
        integrity.canonical_bytes(state)
    )

    tampered = json.loads(receipt.read_text(encoding="utf-8"))
    tampered["bootstrap_version"] = "0.0.0"
    receipt.write_bytes(integrity.canonical_bytes(tampered))
    with pytest.raises(integrity.IntegrityError, match="payload digest changed"):
        integrity.load_receipt(receipt)


def test_receipt_rejects_noncanonical_json_and_unsafe_mode(tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.json"
    state = minimal_state()
    payload = integrity.payload_with_integrity(state)
    receipt.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    receipt.chmod(0o600)
    with pytest.raises(integrity.IntegrityError, match="not canonical JSON"):
        integrity.load_receipt(receipt)

    write_receipt(receipt, state)
    receipt.chmod(0o620)
    with pytest.raises(integrity.IntegrityError, match="group/world-writable"):
        integrity.load_receipt(receipt)


def test_receipt_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    write_receipt(target, minimal_state())
    receipt = tmp_path / "receipt.json"
    receipt.symlink_to(target)
    with pytest.raises(integrity.IntegrityError, match="regular non-symlink"):
        integrity.load_receipt(receipt)


def test_build_uses_exclusive_owner_only_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output = tmp_path / "receipt.json"
    state = minimal_state()
    monkeypatch.setattr(integrity, "collect_state", lambda **_: state)
    monkeypatch.setattr(
        integrity.sys,
        "argv",
        [
            str(MODULE_PATH),
            "build",
            "--output",
            str(output),
            "--cloak-runtime",
            str(tmp_path / "cloak"),
            "--cloak-binary",
            str(tmp_path / "binary"),
            "--node-runtime",
            str(tmp_path / "node"),
            "--config-runtime",
            str(tmp_path / "config"),
        ],
    )
    assert integrity.main() == 0
    assert os.stat(output).st_mode & 0o777 == 0o600
    assert (
        integrity.load_receipt(output)["bootstrap_version"]
        == integrity.BOOTSTRAP_VERSION
    )

    monkeypatch.setattr(integrity.sys, "argv", list(integrity.sys.argv))
    assert integrity.main() == 1
    assert (
        integrity.load_receipt(output)["bootstrap_version"]
        == integrity.BOOTSTRAP_VERSION
    )
