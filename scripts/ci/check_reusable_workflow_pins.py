#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re
import sys


PIN = re.compile(
    r"uses:\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/\.github/workflows/"
    r"([A-Za-z0-9_.-]+\.ya?ml)@([0-9a-f]{40})\s+#\s+(\S+)"
)


def validate(root: pathlib.Path) -> list[str]:
    registry_path = root / "config/reusable-workflow-pins.json"
    value = json.loads(registry_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    if value.get("schema_version") != 1 or not isinstance(value.get("repositories"), list):
        return [f"{registry_path}: invalid reusable-workflow pin registry"]
    registry: dict[str, tuple[str, str]] = {}
    for row in value["repositories"]:
        repository = row.get("repository", "")
        version = row.get("version", "")
        commit = row.get("commit", "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            problems.append(f"{registry_path}: invalid repository {repository!r}")
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
            problems.append(f"{registry_path}: invalid release {version!r} for {repository}")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            problems.append(f"{registry_path}: invalid commit for {repository}")
        if repository in registry:
            problems.append(f"{registry_path}: duplicate repository {repository}")
        registry[repository] = (version, commit)

    seen: set[str] = set()
    for path in sorted((root / ".github/workflows").glob("*.yml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "uses:" not in line or "/.github/workflows/" not in line:
                continue
            match = PIN.search(line)
            if match is None:
                problems.append(f"{path}:{number}: reusable workflow needs full SHA and release comment")
                continue
            repository, _workflow, commit, version = match.groups()
            expected = registry.get(repository)
            if expected is None:
                problems.append(f"{path}:{number}: {repository} is not registered")
                continue
            seen.add(repository)
            if (version, commit) != expected:
                problems.append(
                    f"{path}:{number}: {repository} pins {commit[:12]} # {version}, "
                    f"want {expected[1][:12]} # {expected[0]}"
                )
    for repository in sorted(set(registry) - seen):
        problems.append(f"{registry_path}: unused reusable-workflow repository {repository}")
    return problems


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[2]
    problems = validate(root)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print("reusable-workflow-pins-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
