#!/usr/bin/env python3
"""Plan, install and verify official Ubuntu harness applications.

This module owns app binaries and package sources only. It never signs in,
creates provider configuration, writes .codex/.claude state, or touches project
repositories. CLI-only harnesses remain explicitly classified instead of
receiving unofficial desktop wrappers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config" / "harness-apps.json"


def load() -> dict:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert data["platform"] == "ubuntu-amd64"
    return data


def installed_package(package: str) -> bool:
    return subprocess.run(
        ["dpkg-query", "-W", "-f=${Status}", package],
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip() == "install ok installed"


def app_checks() -> dict[str, dict]:
    return {
        "antigravity": {"path": "/opt/antigravity/2.5.5/Antigravity IDE/antigravity-ide"},
        "claude-code": {"package": "claude-desktop"},
        "codex": {"package": "chatgpt"},
        "cursor": {"package": "cursor"},
    }


def verify(data: dict) -> int:
    failures = 0
    checks = app_checks()
    for name, spec in data["apps"].items():
        cli = shutil.which(spec["cli"])
        if not cli:
            print(f"FAIL {name}: CLI {spec['cli']} is missing")
            failures += 1
            continue
        if not spec["desktop"]:
            print(f"OK   {name}: CLI present; no official Ubuntu desktop app declared")
            continue
        check = checks[name]
        if "package" in check:
            ok = installed_package(check["package"])
        else:
            ok = Path(check["path"]).is_file()
        if ok:
            print(f"OK   {name}: CLI and desktop application present")
        else:
            print(f"FAIL {name}: CLI present but desktop application is missing")
            failures += 1
    return failures


def install_antigravity(spec: dict) -> None:
    with tempfile.TemporaryDirectory(prefix="harness-apps-") as tmp:
        archive = Path(tmp) / "antigravity.tar.gz"
        urllib.request.urlretrieve(spec["url"], archive)
        if archive.stat().st_size != spec["bytes"]:
            raise SystemExit("Antigravity artifact size differs from the manifest")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != spec["sha256"]:
            raise SystemExit("Antigravity artifact digest differs from the manifest")
        stage = Path(tmp) / "unpacked"
        stage.mkdir()
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(stage, filter="data")
        source = stage / "Antigravity IDE"
        if not (source / "antigravity-ide").is_file():
            raise SystemExit("Antigravity archive has an unexpected shape")
        root = Path(spec["install_root"])
        subprocess.run(["sudo", "install", "-d", "-m", "755", str(root)], check=True)
        subprocess.run(["sudo", "cp", "-a", str(source), str(root.parent)], check=True)
        binary = root / "Antigravity IDE" / "antigravity-ide"
        sandbox = root / "Antigravity IDE" / "chrome-sandbox"
        subprocess.run(["sudo", "chmod", "755", str(binary)], check=True)
        subprocess.run(["sudo", "chown", "root:root", str(sandbox)], check=True)
        subprocess.run(["sudo", "chmod", "4755", str(sandbox)], check=True)


def install(data: dict) -> int:
    packages = [
        spec["package"]
        for spec in data["apps"].values()
        if spec["desktop"] and spec["install"] in {"apt", "apt-package"}
    ]
    if packages:
        subprocess.run(["sudo", "apt-get", "install", "-y", *packages], check=True)
    spec = data["apps"]["antigravity"]
    if not Path(app_checks()["antigravity"]["path"]).is_file():
        install_antigravity(spec)
    return verify(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("plan", "install", "verify"))
    args = parser.parse_args()
    data = load()
    if args.operation == "plan":
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    if args.operation == "install":
        return install(data)
    return verify(data)


if __name__ == "__main__":
    raise SystemExit(main())
