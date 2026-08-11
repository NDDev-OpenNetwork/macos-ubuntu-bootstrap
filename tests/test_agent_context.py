"""The agent-facing context has one canonical source, and its rules are gates.

Four hand-maintained layers used to describe this repository: `AGENTS.md`,
`.claude/CLAUDE.md`, 23 Serena memories and a compiled GDS projection. They
drifted -- the Claude file did not know the `desktop-builds` profile and used a
retired name for the server policy, and the memory index claimed three tracked
memories when there were 23.

These tests hold the collapsed shape in place: one guide, one import, and rules
that are checked rather than asserted.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"
CLAUDE = ROOT / ".claude/CLAUDE.md"
MEMORIES = ROOT / ".serena/memories"
CONTRACT = json.loads((ROOT / "config/rldyour-contract.json").read_text(encoding="utf-8"))
WORKFLOWS = ROOT / ".github/workflows"


# ----------------------------- context topology -----------------------------


def test_claude_imports_the_canonical_guide_instead_of_restating_it() -> None:
    text = CLAUDE.read_text(encoding="utf-8")
    assert "@AGENTS.md" in text, "CLAUDE.md must import the canonical guide"
    # A second copy of the project contract is what drifted last time.
    assert len(text.splitlines()) <= 60, (
        "CLAUDE.md is a delta, not a second specification"
    )


def test_pins_are_not_duplicated_into_the_agent_context() -> None:
    """Exact versions belong to the contract; prose copies of them go stale."""
    claude = CLAUDE.read_text(encoding="utf-8")
    support = CONTRACT["runtime_support"]
    for field in ("ubuntu_node_lts", "ubuntu_uv", "ubuntu_bun", "ubuntu_go", "ubuntu_dart"):
        assert support[field] not in claude, (
            f"CLAUDE.md pins {field}={support[field]}; the contract owns that"
        )


def test_no_agent_surface_names_a_retired_profile_or_policy() -> None:
    known_profiles = set(CONTRACT["targets"]["ubuntu"]["profiles"])
    policies = {
        spec["execution_policy"] for spec in CONTRACT["targets"]["ubuntu"]["profiles"].values()
    }
    for path in (AGENTS, CLAUDE):
        text = path.read_text(encoding="utf-8")
        assert "server-build-runtime" not in text, (
            f"{path.name} uses a policy name the contract retired"
        )
        if "--profile" in text:
            assert "desktop-builds" in text, f"{path.name} omits a supported profile"
    assert "container-execution-only" in policies


def test_the_memory_corpus_stays_small_and_self_describing() -> None:
    memories = sorted(MEMORIES.glob("*.md"))
    assert len(memories) <= 3, (
        f"{len(memories)} tracked memories; the corpus is derived context, not a "
        "second specification"
    )
    for memory in memories:
        text = memory.read_text(encoding="utf-8")
        # A memory that repeats a pin is a copy that will go stale.
        assert CONTRACT["adapter"]["version"] not in text, (
            f"{memory.name} pins the adapter version"
        )


# ----------------------------- rules as gates -----------------------------


EXEMPTION = "exposes no `runner` input"


def _reusable_callers() -> list[tuple[Path, bool, bool, bool]]:
    """(workflow, has a `with:` block, names `runner`, documented as exempt).

    Parsed line-wise on purpose: the locked test environment carries no YAML
    reader, and pulling one in for a lint would be a supply-chain change for a
    convenience. These files have one `uses:` per job at a fixed indent.
    """
    callers: list[tuple[Path, bool, bool]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if "uses: NDDev-it-com/ci-workflows/" not in line:
                continue
            indent = len(line) - len(line.lstrip())
            has_with = names_runner = exempt = False
            for follower in lines[index + 1 :]:
                if follower.strip() and (len(follower) - len(follower.lstrip())) < indent:
                    break  # left the job
                stripped = follower.strip()
                if EXEMPTION in stripped:
                    exempt = True
                elif stripped == "with:":
                    has_with = True
                elif has_with and stripped.startswith("runner:"):
                    names_runner = True
            callers.append((path, has_with, names_runner, exempt))
    return callers


def test_every_reusable_caller_that_can_name_a_runner_does() -> None:
    """This was prose in two files and enforced by nothing.

    The repository is public, so `pull_request` runs untrusted fork code. The
    reusable's `runner` default belongs to the pinned commit, not to this
    repository, and several of those reusables default it to the estate's
    self-hosted label -- so a routine Dependabot pin bump could move fork PRs
    onto trusted infrastructure with no diff here to review.
    """
    callers = _reusable_callers()
    assert callers, "no ci-workflows callers found"
    missing = [
        path.name
        for path, has_with, names_runner, exempt in callers
        if has_with and not names_runner and not exempt
    ]
    assert missing == [], (
        f"these callers pass inputs but never name a runner: {missing}. "
        "If a reusable exposes no `runner` input, say so in a comment."
    )
    # An exemption is a claim about the pinned commit and must be re-checked
    # when the pin moves, so it is recorded next to the call rather than
    # remembered.
    exempted = [path.name for path, _w, _r, exempt in callers if exempt]
    assert exempted == ["cross-platform.yml", "pr-hygiene.yml"], (
        f"the exemption list changed: {exempted}. Verify against the reusable's "
        "inputs at the pinned commit before accepting it."
    )


@pytest.mark.parametrize("path", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_reusable_workflows_are_pinned_to_an_exact_commit(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.search(r"uses:\s*(NDDev-it-com/ci-workflows/[^@]+)@(\S+)", line)
        if match:
            assert re.fullmatch(r"[0-9a-f]{40}", match.group(2)), (
                f"{path.name} uses a mutable ref: {match.group(2)}"
            )
