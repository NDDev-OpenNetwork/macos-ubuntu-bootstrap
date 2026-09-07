#!/usr/bin/env python3
"""Compare the declared and live ordinary-merge status-check policy.

An empty, well-formed context list is a valid advisory policy. API failures and
malformed responses remain errors. Release publication checks are independent.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIRROR = ROOT / ".github/rulesets/branch-main.json"
LIVE_ENDPOINT = "/repos/{repo}/rules/branches/main"
DEFAULT_REPO = "NDDev-OpenNetwork/macos-ubuntu-bootstrap"


class ContextError(RuntimeError):
    """The declared and observed required-check policies do not agree."""


def contexts_from_rules(rules: object, source: str) -> list[str]:
    if not isinstance(rules, list):
        raise ContextError(f"{source}: rules must be an array")
    contexts: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("type"), str):
            raise ContextError(f"{source}: malformed rule")
        if rule["type"] != "required_status_checks":
            continue
        parameters = rule.get("parameters")
        checks = parameters.get("required_status_checks") if isinstance(parameters, dict) else None
        if not isinstance(checks, list):
            raise ContextError(f"{source}: malformed required status checks")
        for check in checks:
            context = check.get("context") if isinstance(check, dict) else None
            if not isinstance(context, str) or not context.strip() or context in contexts:
                raise ContextError(f"{source}: empty, duplicate or malformed context")
            contexts.append(context)
    return sorted(contexts)


def mirror_contexts(path: Path = MIRROR) -> list[str]:
    ruleset = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(ruleset, dict) or "rules" not in ruleset:
        raise ContextError(f"{path}: malformed ruleset mirror")
    return contexts_from_rules(ruleset["rules"], str(path))


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

    try:
        rules = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ContextError(f"{endpoint}: malformed JSON") from exc
    return contexts_from_rules(rules, endpoint)


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
