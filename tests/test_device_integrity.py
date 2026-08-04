from __future__ import annotations

import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/device_integrity.py"
SPEC = importlib.util.spec_from_file_location("device_integrity", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
di = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(di)


# ----------------------------- helpers -----------------------------


def write_receipt(path: Path, state: dict[str, object]) -> None:
    """Write a canonical receipt with payload_sha256, mode 0600."""
    path.write_bytes(di.canonical_bytes(di.payload_with_integrity(state)))
    path.chmod(0o600)


def write_canonical(path: Path, data: dict[str, object]) -> None:
    """Write canonical JSON without the integrity field, mode 0600."""
    path.write_bytes(di.canonical_bytes(data))
    path.chmod(0o600)


def minimal_state() -> dict[str, object]:
    """A receipt-shaped dict with the mandatory top-level fields.

    The runtime_hosts/pinned_source_tools/user_tools/desktop_entries keys are
    kept empty so build-time and verify-time collect_state are not needed for
    the structural-integrity tests below.
    """
    return {
        "schema": di.SCHEMA,
        "owner": di.OWNER,
        "bootstrap_version": di.BOOTSTRAP_VERSION,
        "home": str(Path.home()),
        "platform": "Linux-x86_64",
        "policy_hashes": {},
        "runtime_hosts": {},
        "pinned_source_tools": {},
        "user_tools": {},
        "desktop_entries": {},
    }


# ----------------------------- canonical serialization -----------------------------


def test_canonical_bytes_is_sorted_compact_with_trailing_newline() -> None:
    payload = {"b": 2, "a": 1, "c": [3, 2, 1]}
    result = di.canonical_bytes(payload)
    assert result.endswith(b"\n")
    decoded = json.loads(result)
    assert decoded == payload
    # Keys must be sorted, separators must be compact (no spaces).
    assert result == b'{"a":1,"b":2,"c":[3,2,1]}\n'


def test_payload_with_integrity_adds_digest_without_mutating_input() -> None:
    original = {"a": 1}
    result = di.payload_with_integrity(original)
    assert "payload_sha256" in result
    assert "payload_sha256" not in original
    assert len(result["payload_sha256"]) == 64
    # The digest must match a re-derivation.
    assert result["payload_sha256"] == di.sha256_bytes(di.canonical_bytes(original))


# ----------------------------- receipt load + integrity -----------------------------


def test_receipt_round_trip_loads_after_write(tmp_path: Path) -> None:
    receipt = tmp_path / "device-receipt.json"
    write_receipt(receipt, minimal_state())
    loaded = di.load_receipt(receipt)
    assert loaded["schema"] == di.SCHEMA
    assert loaded["owner"] == di.OWNER
    assert "payload_sha256" in loaded


def test_receipt_rejects_noncanonical_json(tmp_path: Path) -> None:
    receipt = tmp_path / "bad.json"
    # Write JSON with spaces (non-canonical) but a valid digest field.
    state = minimal_state()
    state["payload_sha256"] = di.sha256_bytes(di.canonical_bytes(state))
    receipt.write_text(json.dumps(state, indent=2))
    receipt.chmod(0o600)
    with pytest.raises(di.IntegrityError, match="not canonical JSON"):
        di.load_receipt(receipt)


def test_receipt_rejects_payload_tampering(tmp_path: Path) -> None:
    """Changing a field after writing must break the payload digest."""
    receipt = tmp_path / "tampered.json"
    write_receipt(receipt, minimal_state())
    # Re-read, mutate a field, re-write canonically WITHOUT fixing the digest.
    data = json.loads(receipt.read_bytes())
    data["platform"] = "Darwin-arm64"
    receipt.write_bytes(di.canonical_bytes(data))
    receipt.chmod(0o600)
    with pytest.raises(di.IntegrityError, match="payload digest changed"):
        di.load_receipt(receipt)


def test_receipt_rejects_wrong_schema(tmp_path: Path) -> None:
    receipt = tmp_path / "wrong-schema.json"
    state = minimal_state()
    state["schema"] = "rldyour-something-else-v1"
    write_receipt(receipt, state)
    with pytest.raises(di.IntegrityError, match="ownership/schema is wrong"):
        di.load_receipt(receipt)


def test_receipt_rejects_wrong_owner(tmp_path: Path) -> None:
    receipt = tmp_path / "wrong-owner.json"
    state = minimal_state()
    state["owner"] = "not-macos-ubuntu-bootstrap"
    write_receipt(receipt, state)
    with pytest.raises(di.IntegrityError, match="ownership/schema is wrong"):
        di.load_receipt(receipt)


def test_receipt_rejects_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    write_receipt(real, minimal_state())
    link = tmp_path / "link.json"
    link.symlink_to(real)
    with pytest.raises(di.IntegrityError, match="regular non-symlink file"):
        di.load_receipt(link)


def test_receipt_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(di.IntegrityError, match="required path is missing"):
        di.load_receipt(tmp_path / "nonexistent.json")


def test_receipt_rejects_group_writable_mode(tmp_path: Path) -> None:
    receipt = tmp_path / "group-writable.json"
    write_receipt(receipt, minimal_state())
    receipt.chmod(0o660)
    with pytest.raises(di.IntegrityError, match="group/world-writable"):
        di.load_receipt(receipt)


# ----------------------------- contract version verification -----------------------------


def test_verify_contract_versions_passes_when_state_matches() -> None:
    """A state whose versions all match the contract must not raise."""
    contract = di.load_contract()
    runtime_support = contract["runtime_support"]
    state = {
        "runtime_hosts": {
            name: {
                # Use _normalize_version to mirror what collect_state would
                # produce — gopls reports "0.23.0" but the contract stores
                # "v0.23.0", and _verify_contract_versions strips the v.
                "normalized": di._normalize_version(runtime_support[field], name),
                "raw": runtime_support[field],
                "path": f"/bin/{name}",
            }
            for name, (_flag, field) in di.RUNTIME_HOSTS.items()
        },
        "pinned_source_tools": {
            name: spec["version"]
            for name, spec in runtime_support[
                di.PINNED_SOURCE_TOOLS_CONTRACT
            ].items()
        },
        "user_tools": {
            name: {
                "installed_version": spec["version"],
                "declared_version": spec["version"],
            }
            for name, spec in contract.get("user_tools", {}).items()
        },
    }
    # Must not raise.
    di._verify_contract_versions(state)


def test_verify_contract_versions_detects_runtime_drift() -> None:
    contract = di.load_contract()
    runtime_support = contract["runtime_support"]
    state = {
        "runtime_hosts": {
            name: {
                "normalized": runtime_support[field],
                "raw": runtime_support[field],
                "path": f"/bin/{name}",
            }
            for name, (_flag, field) in di.RUNTIME_HOSTS.items()
        },
        "pinned_source_tools": {},
        "user_tools": {},
    }
    # Introduce a drift in node.
    state["runtime_hosts"]["node"]["normalized"] = "0.0.0"
    with pytest.raises(di.IntegrityError, match="node: installed 0.0.0"):
        di._verify_contract_versions(state)


def test_verify_contract_versions_detects_absent_runtime() -> None:
    state = {
        "runtime_hosts": {
            name: {"normalized": None, "raw": "absent", "path": f"/bin/{name}"}
            for name, _ in di.RUNTIME_HOSTS.items()
        },
        "pinned_source_tools": {},
        "user_tools": {},
    }
    with pytest.raises(di.IntegrityError, match="absent"):
        di._verify_contract_versions(state)


def test_verify_contract_versions_detects_user_tool_drift() -> None:
    contract = di.load_contract()
    declared = list(contract.get("user_tools", {}))
    if not declared:
        pytest.skip("contract declares no user tools")
    name = declared[0]
    declared_version = contract["user_tools"][name]["version"]
    state = {
        "runtime_hosts": {},
        "pinned_source_tools": {},
        "user_tools": {
            name: {
                "installed_version": "0.0.0",
                "declared_version": declared_version,
            }
        },
    }
    with pytest.raises(di.IntegrityError, match=f"{name}: installed 0.0.0"):
        di._verify_contract_versions(state)


# ----------------------------- contract parity (static) -----------------------------


def test_contract_has_new_sections() -> None:
    """The contract must declare the sections this feature relies on."""
    contract = di.load_contract()
    assert "user_tools" in contract, "contract missing user_tools section"
    assert "desktop_entries" in contract, "contract missing desktop_entries section"
    assert (
        "ubuntu_apt_packages" in contract
    ), "contract missing ubuntu_apt_packages section"


def test_herdr_declared_in_contract_and_install_sh() -> None:
    """herdr must be declared in both the contract and the bash installer."""
    contract = di.load_contract()
    assert "herdr" in contract["user_tools"], "herdr not in contract user_tools"
    assert (
        contract["user_tools"]["herdr"]["version"] == "0.7.5"
    ), "herdr version mismatch in contract"

    installer = (ROOT / "scripts/ubuntu/install.sh").read_text(encoding="utf-8")
    assert "USER_TOOLS=(" in installer, "USER_TOOLS array missing from install.sh"
    assert (
        "herdr;0.7.5;raw" in installer
    ), "herdr row missing from USER_TOOLS array in install.sh"


def test_desktop_template_exists() -> None:
    template = ROOT / "templates/desktop/herdr.desktop"
    assert template.is_file(), f"desktop template missing: {template}"
    text = template.read_text(encoding="utf-8")
    assert "Exec=ptyxis" in text, "desktop template missing Ptyxis Exec line"
    assert "desktop-entry-herdr-v1" in text, "desktop template missing managed marker"


# ----------------------------- build / verify CLI -----------------------------


def test_build_writes_canonical_receipt(tmp_path: Path) -> None:
    output = tmp_path / "built.json"
    # build uses the real machine state, which is fine — we only assert the
    # output is canonical and loadable.
    rc = _run_cli("build", "--output", str(output))
    assert rc == 0
    assert output.exists()
    loaded = di.load_receipt(output)
    assert loaded["schema"] == di.SCHEMA


def test_verify_cli_returns_zero_on_valid_receipt(tmp_path: Path) -> None:
    """verify subcommand via CLI must exit 0 and print PROVEN for a fresh receipt."""
    receipt = tmp_path / "verify.json"
    assert _run_cli("build", "--output", str(receipt)) == 0
    assert _run_cli("verify", "--receipt", str(receipt)) == 0


def test_verify_cli_json_output(tmp_path: Path) -> None:
    """verify --json must emit a canonical JSON status envelope."""
    import io
    import sys

    receipt = tmp_path / "verify-json.json"
    assert _run_cli("build", "--output", str(receipt)) == 0

    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        rc = _run_cli("verify", "--receipt", str(receipt), "--json")
    finally:
        output = sys.stdout.getvalue()
        sys.stdout = old_stdout

    assert rc == 0
    result = json.loads(output)
    assert result["status"] == "PROVEN"
    assert "payload_sha256" in result


def test_metadata_only_cli(tmp_path: Path) -> None:
    """metadata-only subcommand must validate receipt self-integrity."""
    receipt = tmp_path / "meta.json"
    assert _run_cli("build", "--output", str(receipt)) == 0
    assert _run_cli("metadata-only", "--receipt", str(receipt)) == 0


def test_is_our_receipt_accepts_valid_receipt(tmp_path: Path) -> None:
    """_is_our_receipt must recognize our schema/owner."""
    receipt = tmp_path / "ours.json"
    assert _run_cli("build", "--output", str(receipt)) == 0
    assert di._is_our_receipt(receipt) is True


def test_is_our_receipt_rejects_foreign_json(tmp_path: Path) -> None:
    """_is_our_receipt must reject a JSON file with wrong schema/owner."""
    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps({"schema": "something-else", "owner": "no-one"}))
    assert di._is_our_receipt(foreign) is False


def test_is_our_receipt_rejects_invalid_json(tmp_path: Path) -> None:
    """_is_our_receipt must return False for unparseable JSON."""
    garbage = tmp_path / "garbage.json"
    garbage.write_text("not json at all")
    assert di._is_our_receipt(garbage) is False


def test_build_overwrites_existing_our_receipt_with_backup(tmp_path: Path) -> None:
    """build must back up an existing our-receipt before rewriting."""
    receipt = tmp_path / "rebuild.json"
    assert _run_cli("build", "--output", str(receipt)) == 0
    # A second build should create a .bak and succeed.
    assert _run_cli("build", "--output", str(receipt)) == 0
    assert (tmp_path / "rebuild.json.bak").exists()


def test_build_refuses_unmanaged_receipt(tmp_path: Path) -> None:
    """build must refuse to overwrite a file that is not one of our receipts."""
    foreign = tmp_path / "foreign.json"
    foreign.write_text(json.dumps({"unrelated": "data"}))
    rc = _run_cli("build", "--output", str(foreign))
    assert rc != 0



def _run_cli(*args: str) -> int:
    """Invoke the script's main() with the given argv."""
    import sys

    old = sys.argv
    sys.argv = [str(MODULE_PATH), *args]
    try:
        return di.main()
    finally:
        sys.argv = old
