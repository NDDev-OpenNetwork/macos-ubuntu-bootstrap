#!/usr/bin/env python3
"""Plan, install and verify official Ubuntu harness applications.

This module owns app binaries and package sources only. It never signs in,
creates provider configuration, writes .codex/.claude state, or touches project
repositories. CLI-only harnesses remain explicitly classified instead of
receiving unofficial desktop wrappers. One install operation converges all
official desktop packages and the verified Antigravity archive together.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config" / "harness-apps.json"
OPENER = urllib.request.build_opener()


def load() -> dict:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("platform") != "ubuntu-amd64":
        raise ValueError("Unsupported harness application manifest")
    contract = json.loads((ROOT / "config/rldyour-contract.json").read_text())
    if set(data.get("apps", {})) != set(contract["harnesses"]["active"]):
        raise ValueError("Desktop manifest identities must match the CLI contract")
    for name, spec in data["apps"].items():
        if spec["cli"] != contract["harnesses"][name]["command"]:
            raise ValueError(f"CLI identity differs from the contract: {name}")
        if not spec["desktop"]:
            continue
        if "package" in spec and not re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", spec["package"]):
            raise ValueError("Invalid Debian package identity")
        if spec["install"] == "apt-package":
            if not re.fullmatch(r"[0-9a-f]{64}", spec.get("sha256", "")) or spec.get("bytes", 0) <= 0:
                raise ValueError(f"Package integrity metadata is required: {name}")
        source = spec.get("apt_source")
        if source:
            keyring = Path(source["keyring"])
            if keyring.parent not in {Path("/etc/apt/keyrings"), Path("/usr/share/keyrings")}:
                raise ValueError("APT keyring is outside the supported directory")
            if Path(source["source_file"]).parent != Path("/etc/apt/sources.list.d"):
                raise ValueError("APT source is outside the supported directory")
        for url in [spec.get("url"), spec.get("source"), (source or {}).get("key_url")]:
            if url and (urlsplit(url).scheme != "https" or urlsplit(url).username):
                raise ValueError("Artifact sources must use credential-free HTTPS")
    return data


def installed_package(package: str) -> bool:
    return subprocess.run(
        ["dpkg-query", "-W", "-f=${Status}", package],
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip() == "install ok installed"


def architecture() -> str:
    return subprocess.check_output(
        ["dpkg", "--print-architecture"], text=True
    ).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_verified(url: str, expected_sha256: str, destination: Path) -> None:
    request = urllib.request.Request(
        url, headers={"User-Agent": "macos-ubuntu-bootstrap/harness-apps"}
    )
    with OPENER.open(request, timeout=120) as response, destination.open(
        "wb"
    ) as output:
        shutil.copyfileobj(response, output)
    if sha256_file(destination) != expected_sha256:
        raise SystemExit(f"Downloaded artifact differs from the manifest: {url}")


def apt_source_text(source: dict, arch: str) -> str:
    architectures = source.get("architectures", [arch])
    if arch not in architectures:
        raise SystemExit(f"APT source does not support this architecture: {arch}")
    keyring = source["keyring"]
    if source.get("format") == "deb822":
        return "\n".join(
            (
                "Types: deb",
                f"URIs: {source['uri']}",
                f"Suites: {source['suite']}",
                f"Components: {' '.join(source['components'])}",
                f"Architectures: {' '.join(architectures)}",
                f"Signed-By: {keyring}",
                "",
            )
        )
    return (
        f"deb [arch={','.join(architectures)} signed-by={keyring}] "
        f"{source['uri']} {source['suite']} {' '.join(source['components'])}\n"
    )


def source_matches(text: str, source: dict, arch: str) -> bool:
    """Accept the same source when a vendor package rewrites its formatting."""
    active = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if source["format"] == "deb":
        return active == [apt_source_text(source, arch).strip()]
    fields = dict(line.split(":", 1) for line in active if ":" in line)
    fields = {key: value.strip() for key, value in fields.items()}
    return (
        fields.get("Types") == "deb"
        and fields.get("URIs") == source["uri"]
        and fields.get("Suites") == source["suite"]
        and fields.get("Components", "").split() == source["components"]
        and fields.get("Signed-By") == source["keyring"]
        and arch in fields.get("Architectures", "").replace(",", " ").split()
        and fields.get("Enabled", "yes") != "no"
    )


def publish_file(source: Path, destination: Path) -> None:
    """Publish a root-owned staged file with an atomic rename and no backup."""
    if destination.is_symlink():
        raise ValueError(f"Symlinked managed destination preserved: {destination}")
    stage = destination.with_name(destination.name + ".harness-apps-stage")
    if stage.exists() or stage.is_symlink():
        raise ValueError(f"Existing publication stage preserved: {stage}")
    subprocess.run(["sudo", "install", "-o", "root", "-g", "root", "-m", "644", str(source), str(stage)], check=True)
    try:
        subprocess.run(["sudo", "mv", "-T", str(stage), str(destination)], check=True)
    finally:
        subprocess.run(["sudo", "rm", "-f", str(stage)], check=True)


def ensure_apt_source(spec: dict, arch: str) -> bool:
    source = spec.get("apt_source")
    if not source:
        return False
    rendered = apt_source_text(source, arch)
    source_path = Path(source["source_file"])
    keyring = Path(source["keyring"])
    expected_keyring_sha256 = source.get("normalized_sha256", source["sha256"])
    if source_path.is_symlink() or keyring.is_symlink():
        raise ValueError("Symlinked APT source or keyring preserved")
    matches = source_path.is_file() and source_matches(source_path.read_text(encoding="utf-8"), source, arch)
    if source_path.exists() and not matches:
        raise ValueError(f"Modified APT source preserved: {source_path}")
    if keyring.exists() and sha256_file(keyring) != expected_keyring_sha256:
        raise ValueError(f"Modified APT keyring preserved: {keyring}")
    if (
        matches
        and keyring.is_file()
        and sha256_file(keyring) == expected_keyring_sha256
    ):
        return False
    with tempfile.TemporaryDirectory(prefix="harness-apt-") as tmp:
        raw_key = Path(tmp) / "vendor-key"
        download_verified(source["key_url"], source["sha256"], raw_key)
        if keyring.suffix == ".gpg":
            normalized_key = Path(tmp) / "vendor-key.gpg"
            subprocess.run(
                ["gpg", "--homedir", tmp, "--no-options", "--batch", "--yes", "--dearmor", "--output", normalized_key, raw_key],
                check=True,
            )
        else:
            normalized_key = raw_key
        if sha256_file(normalized_key) != expected_keyring_sha256:
            raise ValueError("Normalized vendor keyring differs from the manifest")
        rendered_source = Path(tmp) / "source"
        rendered_source.write_text(rendered, encoding="utf-8")
        subprocess.run(["sudo", "install", "-d", "-m", "755", str(keyring.parent)], check=True)
        publish_file(normalized_key, keyring)
        publish_file(rendered_source, source_path)
    return True


def app_binary(spec: dict) -> Path:
    return Path(spec["install_root"]) / "Antigravity IDE" / "antigravity-ide"


def verify(data: dict) -> int:
    failures = 0
    for name, spec in data["apps"].items():
        cli = shutil.which(spec["cli"])
        if not cli:
            print(f"FAIL {name}: CLI {spec['cli']} is missing")
            failures += 1
            continue
        if not spec["desktop"]:
            print(f"OK   {name}: CLI present; no official Ubuntu desktop app declared")
            continue
        if "package" in spec:
            ok = installed_package(spec["package"])
        else:
            ok = app_binary(spec).is_file() and os.access(app_binary(spec), os.X_OK)
        if ok:
            print(f"OK   {name}: CLI and desktop application present")
        else:
            print(f"FAIL {name}: CLI present but desktop application is missing")
            failures += 1
    return failures


def install_antigravity(spec: dict) -> None:
    with tempfile.TemporaryDirectory(prefix="harness-apps-") as tmp:
        archive = Path(tmp) / "antigravity.tar.gz"
        download_verified(spec["url"], spec["sha256"], archive)
        if archive.stat().st_size != spec["bytes"]:
            raise SystemExit("Antigravity artifact size differs from the manifest")
        stage = Path(tmp) / "unpacked"
        stage.mkdir()
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(stage, filter="data")
        source = stage / "Antigravity IDE"
        if not (source / "antigravity-ide").is_file():
            raise SystemExit("Antigravity archive has an unexpected shape")
        root = Path(spec["install_root"])
        subprocess.run(["sudo", "install", "-d", "-m", "755", str(root)], check=True)
        subprocess.run(["sudo", "cp", "-a", str(source), str(root)], check=True)
        subprocess.run(["sudo", "chown", "-R", "root:root", str(root)], check=True)
        binary = root / "Antigravity IDE" / "antigravity-ide"
        sandbox = root / "Antigravity IDE" / "chrome-sandbox"
        subprocess.run(["sudo", "chmod", "755", str(binary)], check=True)
        subprocess.run(["sudo", "chown", "root:root", str(sandbox)], check=True)
        subprocess.run(["sudo", "chmod", "4755", str(sandbox)], check=True)
        desktop = Path(tmp) / "antigravity-ide.desktop"
        desktop.write_text(
            "[Desktop Entry]\nType=Application\nName=Antigravity IDE\n"
            f'Exec="{binary}" %F\nTerminal=false\nCategories=Development;IDE;\n',
            encoding="utf-8",
        )
        subprocess.run(
            ["sudo", "install", "-m", "644", str(desktop),
             "/usr/share/applications/antigravity-ide.desktop"], check=True
        )


def install_deb_package(spec: dict) -> None:
    with tempfile.TemporaryDirectory(prefix="harness-deb-") as tmp:
        archive = Path(tmp) / f"{spec['package']}.deb"
        request = urllib.request.Request(
            spec["source"], headers={"User-Agent": "macos-ubuntu-bootstrap/harness-apps"}
        )
        with OPENER.open(request, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        if "bytes" in spec and archive.stat().st_size != spec["bytes"]:
            raise SystemExit(f"Downloaded package size differs from the manifest: {spec['package']}")
        if "sha256" in spec and sha256_file(archive) != spec["sha256"]:
            raise SystemExit(f"Downloaded package differs from the manifest: {spec['package']}")
        subprocess.run(["sudo", "apt-get", "install", "-y", str(archive)], check=True)


def install(data: dict) -> int:
    arch = architecture()
    if arch != "amd64":
        raise ValueError("Harness desktop installation supports Ubuntu amd64 only")
    apt_packages = []
    deb_packages = []
    source_changed = False
    for spec in data["apps"].values():
        if not spec["desktop"]:
            continue
        if spec["install"] == "apt":
            source_changed |= ensure_apt_source(spec, arch)
            apt_packages.append(spec["package"])
        elif spec["install"] == "apt-package" and not installed_package(spec["package"]):
            deb_packages.append(spec)
    if source_changed or apt_packages:
        subprocess.run(["sudo", "apt-get", "update"], check=True)
    if apt_packages:
        subprocess.run(["sudo", "apt-get", "install", "-y", *apt_packages], check=True)
    for spec in deb_packages:
        install_deb_package(spec)
    spec = data["apps"]["antigravity"]
    if not app_binary(spec).is_file():
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
