from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("support_evidence", ROOT / "scripts/support_evidence.py")
assert SPEC and SPEC.loader
support_evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(support_evidence)

MATRIX = json.loads((ROOT / "config/support-evidence-matrix.json").read_text(encoding="utf-8"))
CONTRACT = json.loads((ROOT / "config/rldyour-contract.json").read_text(encoding="utf-8"))


def test_canonical_matrix_validates_and_is_deterministic() -> None:
    support_evidence.validate_matrix(MATRIX, CONTRACT)
    assert CONTRACT["support_evidence"]["path"] == "config/support-evidence-matrix.json"
    first = support_evidence.resolve_lane(MATRIX, "ubuntu-desktop-no-gui", "x86_64")
    second = support_evidence.resolve_lane(MATRIX, "ubuntu-desktop-no-gui", "AMD64")
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


@pytest.mark.parametrize("arch,expected", [("x64", "amd64"), ("aarch64", "arm64")])
def test_architecture_aliases_are_explicit(arch: str, expected: str) -> None:
    assert support_evidence.resolve_lane(MATRIX, "ubuntu-desktop-no-gui", arch)["architecture"] == expected


def test_unknown_lane_and_unsupported_architecture_fail_closed() -> None:
    with pytest.raises(support_evidence.MatrixError, match="unknown or ambiguous"):
        support_evidence.resolve_lane(MATRIX, "invented", "arm64")
    with pytest.raises(support_evidence.MatrixError, match="not declared"):
        support_evidence.resolve_lane(MATRIX, "sandbox-server-rootless", "arm64")
    with pytest.raises(support_evidence.MatrixError, match="unsupported evidence architecture"):
        support_evidence.resolve_lane(MATRIX, "macos-gui", "riscv64")


def test_duplicate_lane_and_composition_fail_closed() -> None:
    duplicate_lane = copy.deepcopy(MATRIX)
    duplicate_lane["evidence_lanes"].append(copy.deepcopy(duplicate_lane["evidence_lanes"][0]))
    with pytest.raises(support_evidence.MatrixError, match="duplicate or invalid evidence lane"):
        support_evidence.validate_matrix(duplicate_lane, CONTRACT)
    duplicate_composition = copy.deepcopy(MATRIX)
    duplicate_composition["support_compositions"].append(copy.deepcopy(duplicate_composition["support_compositions"][0]))
    with pytest.raises(support_evidence.MatrixError, match="duplicate or invalid composition"):
        support_evidence.validate_matrix(duplicate_composition, CONTRACT)


def test_missing_lane_coverage_fails_closed() -> None:
    matrix = copy.deepcopy(MATRIX)
    matrix["evidence_lanes"] = matrix["evidence_lanes"][:-1]
    with pytest.raises(support_evidence.MatrixError, match="lane set drift"):
        support_evidence.validate_matrix(matrix, CONTRACT)


def test_known_gaps_are_typed_optional_and_tracked() -> None:
    assert {gap["tracking_issue"] for gap in MATRIX["known_evidence_gaps"]} == {55, 56, 57}
    assert all(gap["requirement"] == "OPTIONAL" for gap in MATRIX["known_evidence_gaps"])
    assert all(gap["status"] == "NOT_PROVEN" for gap in MATRIX["known_evidence_gaps"])
    assert {gap["id"] for gap in MATRIX["known_evidence_gaps"]} >= {
        "ubuntu-26.04-hosted-runtime", "interactive-privilege-prompts",
        "reboot-gui-live-ssh-firewall", "ubuntu-amd64-gui-runtime",
        "ubuntu-arm64-rootless-runtime",
    }


def test_declared_hosted_artifact_count_is_exactly_thirteen() -> None:
    assert MATRIX["expected_hosted_artifact_instances"] == 13
    assert sum(len(lane["architectures"]) for lane in MATRIX["evidence_lanes"]) == 13


def test_installation_audit_covers_every_contract_install_domain() -> None:
    audit_ids = {item["id"] for item in MATRIX["installation_audit"]}
    assert {
        "ai-cli-codex", "ai-cli-claude-code", "ai-cli-grok-build",
        "macos-homebrew-formulae-and-casks", "ubuntu-apt-baseline",
        "ubuntu-pinned-source-tools", "ubuntu-node-uv-bun",
        "ubuntu-go-gopls-rust-dart", "herdr", "google-chrome", "rustdesk",
        "telegram", "terminal-git-payloads", "ubuntu-docker",
        "ubuntu-server-hardening",
    } == audit_ids


def test_required_unproven_and_tier_escalation_fail_closed() -> None:
    required_unproven = copy.deepcopy(MATRIX)
    capability = required_unproven["evidence_lanes"][0]["capabilities"][0]
    capability["status"] = "NOT_PROVEN"
    capability["required_tier"] = "REAL_HOST_REQUIRED"
    with pytest.raises(support_evidence.MatrixError, match="REQUIRED capability must be PROVEN"):
        support_evidence.validate_matrix(required_unproven, CONTRACT)

    escalation = copy.deepcopy(MATRIX)
    optional = escalation["evidence_lanes"][0]["capabilities"][1]
    optional["status"] = "PROVEN"
    with pytest.raises(support_evidence.MatrixError, match="PROVEN cannot claim"):
        support_evidence.validate_matrix(escalation, CONTRACT)


def test_optional_not_proven_is_honest_and_does_not_weaken_required_gate() -> None:
    lane = support_evidence.resolve_lane(MATRIX, "macos-gui", "arm64")
    payload = {"capabilities": copy.deepcopy(lane["capabilities"])}
    result = support_evidence.finalize_evidence(payload, "success")
    assert result["result"] == "success"
    assert any(item["status"] == "NOT_PROVEN" for item in result["capabilities"])
    assert all(item["status"] == "PROVEN" for item in result["capabilities"] if item["requirement"] == "REQUIRED")


def test_finalize_rejects_success_with_required_unproven() -> None:
    payload = {"capabilities": [{"id": "core", "requirement": "REQUIRED", "status": "NOT_PROVEN"}]}
    with pytest.raises(support_evidence.MatrixError, match="left REQUIRED capability unproven"):
        support_evidence.finalize_evidence(payload, "success")


def test_workflow_and_runner_script_lane_sets_match_matrix() -> None:
    workflow = (ROOT / ".github/workflows/platform-evidence.yml").read_text(encoding="utf-8")
    runner = (ROOT / "scripts/ci/platform-evidence.sh").read_text(encoding="utf-8")
    for lane in MATRIX["evidence_lanes"]:
        assert lane["lane"] in workflow
        assert lane["lane"] in runner
