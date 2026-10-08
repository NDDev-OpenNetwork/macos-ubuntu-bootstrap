#!/usr/bin/env python3
"""Install reproducible, explicit full-autonomy CLI wrappers.

The wrappers are bootstrap-owned launchers only. They never edit vendor
configuration, credentials, project files, or model settings.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config/ai-launchers.json"
MARKER = "macos-ubuntu-bootstrap-managed-ai-launcher-v2"


def load() -> dict:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("vendor_configuration_mutated") is not False:
        raise ValueError("invalid AI launcher policy")
    names = [x["name"] for x in data["launchers"]]
    if len(names) != len(set(names)) or data["dispatcher"]["name"] in names:
        raise ValueError("duplicate launcher identity")
    return data


def render(entry: dict) -> str:
    env = entry.get("env", {})
    prefix = "exec "
    if env:
        prefix = "exec env " + " ".join(f"{shlex.quote(k)}={shlex.quote(v)}" for k, v in env.items()) + " "
    command = " ".join([shlex.quote(entry["command"]), *(shlex.quote(x) for x in entry["args"])])
    return f"#!/bin/sh\n# Managed by {MARKER}\n# Explicit full-auto wrapper; vendor configuration remains untouched.\n{prefix}{command} \"$@\"\n"


def render_dispatcher(data: dict) -> str:
    cases = []
    for key, target in data["dispatcher"]["targets"].items():
        cases.append(f"  {key}) shift; exec \"$HOME/.local/bin/{target}\" \"$@\" ;;")
    for entry in data["launchers"]:
        for alias in entry.get("aliases", []):
            cases.append(f"  {alias}) shift; exec \"$HOME/.local/bin/{entry['name']}\" \"$@\" ;;")
    return "#!/bin/sh\n# Managed by %s\ncase \"${1:-}\" in\n%s\n  *) echo \"usage: ai-full <harness> [args...]\" >&2; exit 2 ;;\nesac\n" % (MARKER, "\n".join(cases))


def install(path: Path, content: str, dry_run: bool) -> None:
    if dry_run:
        print(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if path.exists() and MARKER not in existing and "macos-ubuntu-bootstrap: ai-launcher-" not in existing:
        raise RuntimeError(f"refusing to overwrite unmanaged launcher: {path}")
    with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=f".{path.name}.", delete=False, encoding="utf-8") as stream:
        stream.write(content)
        temporary = Path(stream.name)
    temporary.chmod(0o755)
    os.replace(temporary, path)


def entries(data: dict) -> list[tuple[str, str]]:
    result = []
    for entry in data["launchers"]:
        content = render(entry)
        result.append((entry["name"], content))
        result.extend((alias, content) for alias in entry.get("aliases", []))
    result.append((data["dispatcher"]["name"], render_dispatcher(data)))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["install", "verify"])
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    data = load()
    for name, content in entries(data):
        destination = Path.home() / ".local/bin" / name
        if args.operation == "install":
            install(destination, content, args.plan)
        elif not destination.is_file() or MARKER not in destination.read_text(encoding="utf-8", errors="replace") or destination.read_text(encoding="utf-8") != content:
            raise SystemExit(f"launcher drift: {destination}")
    if args.operation == "install" and not args.plan:
        print(json.dumps({"installed": len(entries(data)), "manifest": str(MANIFEST), "vendor_configuration_mutated": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
