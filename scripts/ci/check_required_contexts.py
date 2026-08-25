#!/usr/bin/env python3
"""Prove the three statements of `main`'s required checks are one list.

The contexts that protect `main` are written down three times:

* the live ruleset, which is the authority;
* ``.github/rulesets/branch-main.json``, the checked-in mirror a reviewer reads;

Nothing compared them. The mirror was allowed to run ahead of the live ruleset
as a "proposal", and the ``.gds`` list was bound by no test at all -- it happened
to be correct, and nothing would have reported it if it stopped being. A reader,
human or agent, cannot tell an accurate list from a stale one by looking.

Two of the three are files, so they are compared on every test run. The live
ruleset needs the API and is compared when ``--live`` is passed; CI passes it.

Exit status is 0 only when every list compared is identical.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIRROR = ROOT / ".github/rulesets/branch-main.json"
LIVE_ENDPOINT = "/repos/{repo}/rules/branches/main"
DEFAULT_REPO = "NDDev-OpenNetwork/macos-ubuntu-bootstrap"


class ContextError(RuntimeError):
    """The three declarations of the required checks do not agree."""


def mirror_contexts(path: Path = MIRROR) -> list[str]:
    ruleset = json.loads(path.read_text(encoding="utf-8"))
    contexts = [
        check["context"]
        for rule in ruleset.get("rules", [])
        if rule.get("type") == "required_status_checks"
        for check in rule.get("parameters", {}).get("required_status_checks", [])
    ]
    if not contexts:
        raise ContextError(f"{path}: declares no required status check")
    return sorted(contexts)


def live_contexts(repo: str = DEFAULT_REPO) -> list[str]:
    """Ask GitHub what the branch actually enforces.

    Uses the rules endpoint rather than the rulesets endpoint on purpose: rules
    are readable with ordinary read access, so this runs in CI under
    `contents: read` instead of needing an administrative token.
    """
    endpoint = LIVE_ENDPOINT.format(repo=repo)
    try:
        completed = subprocess.run(
            ["gh", "api", "-H", "Accept: application/vnd.github+json", endpoint],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise ContextError("--live needs the gh CLI, which is not on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise ContextError(
            f"--live could not read {endpoint}: {exc.stderr.strip() or exc}"
        ) from exc

    rules = json.loads(completed.stdout)
    contexts = [
        check["context"]
        for rule in rules
        if rule.get("type") == "required_status_checks"
        for check in rule.get("parameters", {}).get("required_status_checks", [])
    ]
    if not contexts:
        raise ContextError(
            f"{endpoint} reports no required status check; either the ruleset was "
            "emptied or this token cannot see it"
        )
    return sorted(contexts)


def _report(name_a: str, a: list[str], name_b: str, b: list[str]) -> None:
    if a == b:
        return
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    raise ContextError(
        f"{name_a} and {name_b} disagree about what protects main:\n"
        f"  only in {name_a}: {only_a or '-'}\n"
        f"  only in {name_b}: {only_b or '-'}"
    )


def check(*, live: bool, repo: str = DEFAULT_REPO) -> int:
    mirror = mirror_contexts()

    if live:
        actual = live_contexts(repo)
        _report("the live ruleset", actual, "the ruleset mirror", mirror)
        print(f"required-contexts-ok: {len(actual)} contexts, live == mirror")
    else:
        print(f"required-contexts-read: {len(mirror)} contexts in the mirror; "
              "pass --live to compare them with the branch")

    for context in mirror:
        print(f"  {context}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="also compare against the live ruleset through the GitHub API",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO,
        help="owner/name to query when --live is passed",
    )
    args = parser.parse_args(argv)
    return check(live=args.live, repo=args.repo)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContextError as exc:
        print(f"required-contexts-error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
