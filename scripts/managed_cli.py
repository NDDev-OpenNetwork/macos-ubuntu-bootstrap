#!/usr/bin/env python3
"""Install the seven vendor CLIs and gddy from reviewed, platform-specific bytes.

Only program payloads and PATH launchers are managed here. Harness configuration,
accounts, credentials and running sessions are outside this installer's boundary.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config/rldyour-contract.json"
MARKER = "macos-ubuntu-bootstrap-managed-cli-v1"


class CLIError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def platform_key() -> str:
    system = {"Darwin": "macos", "Linux": "linux"}.get(os.uname().sysname)
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64"}.get(os.uname().machine)
    if system is None or arch is None:
        raise CLIError("no reviewed CLI artifacts for this platform")
    return f"{system}/{arch}"


def specifications(contract: dict) -> dict[str, dict]:
    entries = {name: contract["harnesses"][name] for name in contract["harnesses"]["active"]}
    entries["gddy"] = contract["user_tools"]["gddy"]
    return entries


def directory(path: Path) -> None:
    if path.is_symlink():
        raise CLIError(f"symlinked program directory preserved: {path}")
    if not path.exists():
        directory(path.parent)
        path.mkdir(mode=0o755)
    metadata = path.stat()
    # Existing shared user parents may be group-writable under Ubuntu's normal
    # private-user-group umask. Preserve their permissions. Program roots and
    # every payload entry are checked more strictly by verify_root/tree_state.
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o002:
        raise CLIError(f"foreign-owned or writable program directory preserved: {path}")


def root_for(home: Path, name: str, spec: dict) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name) or not re.fullmatch(r"[A-Za-z0-9.+-]+", spec["version"]):
        raise CLIError("unsafe program identity or version")
    return home / ".local/share/rldyour/cli" / name / spec["version"]


def artifact_for(spec: dict, platform: str) -> dict:
    artifact = spec.get("artifacts", {}).get(platform)
    if not isinstance(artifact, dict):
        raise CLIError(f"no reviewed artifact for {spec['command']} on {platform}")
    if not re.fullmatch(r"[0-9a-f]{64}", artifact.get("sha256", "")) or artifact.get("bytes", 0) <= 0:
        raise CLIError("artifact digest and byte length are required")
    if not artifact.get("url", "").startswith("https://"):
        raise CLIError("artifact URL must use HTTPS")
    return artifact


def download(artifact: dict, destination: Path) -> None:
    subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error",
                    "--proto", "=https", "--proto-redir", "=https", "--connect-timeout", "20",
                    "--max-time", "300", "--output", str(destination), artifact["url"]],
                   check=True, timeout=310)
    if destination.stat().st_size != artifact["bytes"] or sha256(destination) != artifact["sha256"]:
        raise CLIError("downloaded artifact differs from reviewed bytes; nothing executed")


def safe_relative(value: str) -> Path:
    item = PurePosixPath(value)
    if item.is_absolute() or ".." in item.parts or not item.parts or "\\" in value:
        raise CLIError(f"unsafe archive path: {value!r}")
    return Path(*item.parts)


def unpack(archive: Path, destination: Path, spec: dict, artifact: dict) -> None:
    if artifact.get("shape", spec.get("shape")) == "raw":
        shutil.copyfile(archive, destination / safe_relative(artifact["member"]))
        return
    if artifact.get("shape", spec.get("shape")) != "gzip-tar":
        raise CLIError("unsupported reviewed archive shape")
    with tarfile.open(archive, "r:gz") as bundle:
        seen = set()
        total = 0
        for member in bundle:
            # Ignore only the conventional archive root directory.
            if member.isdir() and member.name in (".", "./"):
                continue
            relative = safe_relative(member.name)
            if relative in seen:
                raise CLIError(f"duplicate archive path: {relative}")
            seen.add(relative)
            if len(seen) > 50000:
                raise CLIError("archive entry count exceeds reviewed payload bound")
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o755)
            elif member.isfile():
                total += member.size
                if total > 3 * 1024**3:
                    raise CLIError("inflated archive exceeds program payload bound")
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                with bundle.extractfile(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
            else:
                raise CLIError(f"archive links and special files are refused: {relative}")


def tree_state(root: Path) -> dict:
    entries = {}
    for path in sorted(root.rglob("*")):
        if path.name == ".bootstrap-cli-receipt.json" and path.parent == root:
            continue
        metadata = path.lstat()
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o022 or path.is_symlink():
            raise CLIError(f"program tree ownership/mode drift: {path}")
        relative = str(path.relative_to(root))
        if path.is_dir():
            entries[relative] = {"type": "directory", "mode": stat.S_IMODE(metadata.st_mode)}
        elif path.is_file():
            entries[relative] = {"type": "file", "mode": stat.S_IMODE(metadata.st_mode), "sha256": sha256(path)}
        else:
            raise CLIError(f"unexpected program payload entry: {path}")
    return entries


def expected_header(name: str, spec: dict, platform: str, artifact: dict) -> dict:
    return {"schema": MARKER, "name": name, "version": spec["version"], "platform": platform,
            "artifact": artifact, "command": spec["command"]}


def verify_root(home: Path, name: str, spec: dict, platform: str) -> dict:
    root = root_for(home, name, spec)
    artifact = artifact_for(spec, platform)
    if root.is_symlink() or not root.is_dir() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o022:
        raise CLIError(f"missing or unsafe managed program tree: {root}")
    receipt = root / ".bootstrap-cli-receipt.json"
    if receipt.is_symlink() or not receipt.is_file() or receipt.stat().st_uid != os.getuid() or stat.S_IMODE(receipt.stat().st_mode) != 0o600:
        raise CLIError(f"missing or unsafe CLI receipt: {receipt}")
    state = json.loads(receipt.read_text())
    header = expected_header(name, spec, platform, artifact)
    if {key: state.get(key) for key in header} != header or state.get("tree") != tree_state(root):
        raise CLIError(f"managed program receipt or payload differs: {name}")
    binary = root / safe_relative(artifact["member"])
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise CLIError(f"missing executable for {name}")
    return {"version": spec["version"], "resolved": str(binary), "receipt_sha256": sha256(receipt)}


def verify(home: Path, name: str, spec: dict, platform: str) -> dict:
    state = verify_root(home, name, spec, platform)
    binary = Path(state["resolved"])
    for command in [spec["command"], *spec.get("aliases", [])]:
        link = home / ".local/bin" / command
        if not link.is_symlink() or link.lstat().st_uid != os.getuid() or os.readlink(link) != str(binary):
            raise CLIError(f"managed CLI launcher differs: {link}")
    return state


def install(home: Path, name: str, spec: dict, platform: str) -> dict:
    artifact = artifact_for(spec, platform)
    root = root_for(home, name, spec)
    directory(root.parent)
    directory(home / ".local/bin")
    commands = [spec["command"], *spec.get("aliases", [])]
    for command in commands:
        if not re.fullmatch(r"[a-z][a-z0-9-]*", command):
            raise CLIError("unsafe command name")
        link = home / ".local/bin" / command
        if (link.exists() or link.is_symlink()) and (link.lstat().st_uid != os.getuid() or not (link.is_file() or link.is_symlink())):
            raise CLIError(f"foreign-owned or non-file launcher preserved: {link}")
    if root.exists() or root.is_symlink():
        verify_root(home, name, spec, platform)
    else:
        with tempfile.TemporaryDirectory(prefix=".stage-", dir=root.parent) as temporary:
            stage = Path(temporary)
            archive = stage / "download"
            payload = stage / "payload"
            payload.mkdir(mode=0o755)
            download(artifact, archive)
            # Independently validate even when a caller supplies its downloader.
            if archive.stat().st_size != artifact["bytes"] or sha256(archive) != artifact["sha256"]:
                raise CLIError("artifact integrity mismatch before extraction")
            unpack(archive, payload, spec, artifact)
            binary = payload / safe_relative(artifact["member"])
            if not binary.is_file() or binary.is_symlink():
                raise CLIError("reviewed executable member is absent")
            binary.chmod(0o755)
            probe_home = stage / "probe-home"
            probe_home.mkdir(mode=0o700)
            probe_environment = {"PATH": os.defpath, "HOME": str(probe_home), "LC_ALL": "C",
                                 "XDG_CONFIG_HOME": str(probe_home / "config"),
                                 "XDG_CACHE_HOME": str(probe_home / "cache"),
                                 "XDG_DATA_HOME": str(probe_home / "data"),
                                 "CODEX_HOME": str(probe_home / "codex")}
            version = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=30,
                                     check=True, env=probe_environment, cwd=stage)
            if not re.search(r"(?<![\d.])" + re.escape(spec["version"]) + r"(?![\d.])", version.stdout + version.stderr):
                raise CLIError(f"reviewed program reports another version: {name}")
            receipt = expected_header(name, spec, platform, artifact)
            receipt["tree"] = tree_state(payload)
            record = payload / ".bootstrap-cli-receipt.json"
            record.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
            record.chmod(0o600)
            os.rename(payload, root)
    binary = root / safe_relative(artifact["member"])
    for command in commands:
        link = home / ".local/bin" / command
        if link.is_symlink() and os.readlink(link) == str(binary):
            continue
        token = str(uuid.uuid4())
        temporary_link = link.parent / f".{command}-{token}"
        temporary_link.symlink_to(binary)
        try:
            if link.exists() or link.is_symlink():
                backup = home / ".local/share/rldyour/backups/cli" / f"{time.time_ns()}-{token}"
                directory(backup)
                backup.chmod(0o700)
                os.rename(link, backup / command)
            os.replace(temporary_link, link)
        finally:
            temporary_link.unlink(missing_ok=True)
    return verify(home, name, spec, platform)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("install", "verify"))
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--platform", choices=("auto", "macos", "ubuntu"), default="auto")
    arguments = parser.parse_args()
    try:
        entries = specifications(json.loads(CONTRACT.read_text()))
        platform = platform_key()
        if arguments.platform != "auto":
            system = "linux" if arguments.platform == "ubuntu" else "macos"
            selected = system + "/" + platform.split("/", 1)[1]
            if not arguments.plan and selected != platform:
                raise CLIError("CLI apply must run on the selected operating system")
            platform = selected
        home = Path.home()
        lock = None
        if arguments.operation == "install" and not arguments.plan:
            lock_root = home / ".local/share/rldyour/cli"
            directory(lock_root)
            lock_path = lock_root / ".install.lock"
            if lock_path.is_symlink():
                raise CLIError("symlinked install lock preserved")
            lock = lock_path.open("a")
            if os.fstat(lock.fileno()).st_uid != os.getuid():
                raise CLIError("foreign-owned install lock preserved")
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for name, spec in entries.items():
            artifact = artifact_for(spec, platform)
            if arguments.plan:
                print(f"[plan] {name} {spec['version']} {artifact['url']} SHA256={artifact['sha256']}")
            else:
                result = install(home, name, spec, platform) if arguments.operation == "install" else verify(home, name, spec, platform)
                print(f"[ok] {name} {result['version']} verified ({platform})")
    except (CLIError, OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        print(f"managed-cli: {error}", file=__import__("sys").stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
