#!/usr/bin/env python3
"""Build and verify the installed device runtime receipt against the contract.

This script mirrors the architecture of ``browser_runtime_integrity.py``: a
canonical-JSON receipt is built from a proven installed state, persisted
atomically, and verified by re-collecting the state and comparing exactly. It
extends the pattern to the *whole device* — not just the browser stack — by
also comparing every declared runtime version and pinned source tool against
``config/rldyour-contract.json``, closing the gap between the contract and the
hardcoded literals the bash installer writes.

Contract sources of truth:

- ``config/rldyour-contract.json`` — pinned versions + SHA-256 for node/uv/bun/
  go/rust/dart/gopls, pinned source tools, user tools (herdr), desktop entries,
  and the apt package manifest.
- per-runtime receipts under ``~/.local/share/rldyour/<runtime>/...`` written by
  ``ubuntu/install.sh`` (format ``ubuntu-runtime-v1``).

The receipt binds a device to its home directory and to the contract the
bootstrap was authored against. Any drift — a tampered binary, an unmanaged
symlink, a contract version that no longer matches what is installed — fails
closed with ``status: NOT_PROVEN``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
OWNER = "macos-ubuntu-bootstrap"
SCHEMA = "rldyour-device-receipt-v1"
BOOTSTRAP_VERSION = "1.0.0"
CONTRACT_PATH = ROOT / "config/rldyour-contract.json"
DEFAULT_RECEIPT = Path.home() / ".local/share/rldyour/device-receipt.json"

# Runtime hosts declared in the contract under runtime_support, mapped to the
# command that reports their version and the contract field that pins it. Each
# entry drives one version comparison during verify.
RUNTIME_HOSTS: dict[str, tuple[str, str]] = {
    # name: (version_flag, contract_field under runtime_support)
    "node": ("--version", "ubuntu_node_lts"),
    "uv": ("--version", "ubuntu_uv"),
    "bun": ("--version", "ubuntu_bun"),
    "go": ("version", "ubuntu_go"),
    "gopls": ("version", "ubuntu_gopls"),
    "rustc": ("--version", "ubuntu_rust"),
    "dart": ("--version", "ubuntu_dart"),
}

# Pinned source tools (contract: runtime_support.ubuntu_pinned_source_tools).
# Each is installed as a managed binary under ~/.local/bin/<name>.
PINNED_SOURCE_TOOLS_CONTRACT = "ubuntu_pinned_source_tools"


class IntegrityError(RuntimeError):
    """A device runtime invariant was not proven."""


# ----------------------------- hashing primitives -----------------------------


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def fail(message: str) -> NoReturn:
    raise IntegrityError(message)


def _current_os() -> str:
    """Return the normalized OS label matching the contract's ``os`` arrays."""
    system = os.uname().sysname
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        return "linux"
    return system.lower()


def _applies_to_current_os(spec: dict[str, Any]) -> bool:
    """Check whether a contract entry's ``os`` array includes this platform.

    Entries without an ``os`` field apply to all platforms (backward
    compatibility). Entries with ``os: ["linux"]`` are skipped on macOS, so a
    Linux-only tool like herdr does not cause a NOT_PROVEN on macOS where it is
    never installed.
    """
    declared_oses = spec.get("os")
    if not declared_oses:
        return True
    # Normalize: "ubuntu" in the contract means Linux (the bootstrap's only
    # Linux target); "linux" is the uname label.
    current = _current_os()
    normalized = {current, "linux" if current == "linux" else current}
    for entry_os in declared_oses:
        if entry_os in normalized or (entry_os == "ubuntu" and current == "linux"):
            return True
    return False


# ----------------------------- safety primitives -----------------------------


def regular_owned(
    path: Path, *, executable: bool = False, enforce_private_mode: bool = True
) -> os.stat_result:
    """Assert a path is a regular, non-symlink, owner-held file.

    ``enforce_private_mode`` additionally refuses a group- or world-writable
    file. That is genuine tamper resistance for a file the installer created
    and owns. It is meaningless for a Git-tracked repository source (Git records
    only the executable bit), so callers reading repository sources pass False.
    """
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        fail(f"required path is missing: {path}")
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        fail(f"path must be a regular non-symlink file: {path}")
    if metadata.st_uid != os.getuid():
        fail(f"path is not owned by the current UID: {path}")
    if enforce_private_mode and metadata.st_mode & 0o022:
        fail(f"path is group/world-writable: {path}")
    if executable and not metadata.st_mode & stat.S_IXUSR:
        fail(f"path is not owner-executable: {path}")
    return metadata


def safe_directory(path: Path, *, enforce_private_mode: bool = True) -> None:
    """Assert a path is a non-symlink directory owned by the current UID.

    ``enforce_private_mode`` additionally refuses a group- or world-writable
    directory. Container directories under ``~/.local/share/rldyour`` are
    routinely ``775`` because the device's umask is ``0002``; the managed
    runtimes inside them (browser-stack, cloakbrowser) are ``700``. We refuse a
    symlink or foreign-owned directory unconditionally, but follow the same
    private-mode opt-out the Git-source hashes use for containers.
    """
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        fail(f"required directory is missing: {path}")
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        fail(f"path must be a non-symlink directory: {path}")
    if metadata.st_uid != os.getuid():
        fail(f"directory is not owned by the current UID: {path}")
    if enforce_private_mode and metadata.st_mode & 0o022:
        fail(f"directory is group/world-writable: {path}")


def ensure_under(path: Path, root: Path, label: str) -> None:
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError):
        fail(f"{label} escaped its managed namespace: {path}")


# ----------------------------- contract access -----------------------------


def load_contract() -> dict[str, Any]:
    regular_owned(CONTRACT_PATH, enforce_private_mode=False)
    try:
        return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError("device contract is unreadable") from exc


def policy_hashes() -> dict[str, str]:
    """Hash every policy/contract/source file that should pin the receipt.

    Changing any of these — the contract, the integrity script itself, the
    installer library, or the desktop template — invalidates the receipt so a
    stale receipt cannot vouch for a newer contract.
    """
    paths = {
        "integrity_policy": Path(__file__).resolve(),
        "installer_policy": ROOT / "scripts/lib/common.sh",
        "ubuntu_installer": ROOT / "scripts/ubuntu/install.sh",
        "contract": CONTRACT_PATH,
    }
    desktop_dir = ROOT / "templates/desktop"
    if desktop_dir.is_dir():
        for entry in sorted(desktop_dir.iterdir()):
            if entry.is_file() and entry.suffix == ".desktop":
                paths[f"desktop_{entry.stem}"] = entry
    for path in paths.values():
        regular_owned(path, enforce_private_mode=False)
    return {name: sha256_file(path) for name, path in paths.items()}


# ----------------------------- state collection -----------------------------


def _run_version(binary: Path, flag: str) -> str:
    """Run ``<binary> <flag>`` in a scrubbed environment and return stdout.

    Mirrors the subprocess idiom of browser_runtime_integrity.py: strip
    PYTHONPATH/PYTHONHOME, capture output, timeout, and chain-raise on failure.
    """
    if not binary.exists():
        return "absent"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    try:
        result = subprocess.run(
            [str(binary), flag],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise IntegrityError(f"version probe failed for {binary.name}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return f"error:{detail or 'no detail'}"
    # Some runtimes print their version to stderr (notably `dart --version`
    # on all platforms, and `go version` on some setups). Merge both streams
    # so the version token is captured regardless of which stream the tool
    # chose — mirroring the `2>&1` pattern the bash installer uses.
    return (result.stdout + result.stderr).strip()


def _normalize_version(raw: str, name: str) -> str:
    """Reduce a version string to the comparable token.

    Each runtime emits its version differently (``v24.18.0``, ``uv 0.11.30``,
    ``go version go1.26.5 linux/amd64``, ``rustc 1.97.1 (...)``). Pull the first
    ``X.Y.Z`` token so the comparison is against the contract's bare semver.
    """
    match = re.search(r"\d+\.\d+\.\d+", raw)
    if not match:
        return raw
    return match.group(0)


def _runtime_versions(bin_dir: Path) -> dict[str, dict[str, str]]:
    """Collect installed versions of every declared runtime host."""
    versions: dict[str, dict[str, str]] = {}
    for name, (flag, _contract_field) in RUNTIME_HOSTS.items():
        binary = shutil.which(name) or str(bin_dir / name)
        raw = _run_version(Path(binary), flag)
        versions[name] = {
            "raw": raw,
            "normalized": _normalize_version(raw, name),
            "path": binary,
        }
    return versions


def _pinned_source_tool_versions(bin_dir: Path) -> dict[str, str]:
    """Collect installed versions of pinned source tools via ``<name> --version``."""
    contract = load_contract()
    declared = contract.get("runtime_support", {}).get(PINNED_SOURCE_TOOLS_CONTRACT, {})
    versions: dict[str, str] = {}
    for name in declared:
        binary = shutil.which(name) or str(bin_dir / name)
        raw = _run_version(Path(binary), "--version")
        versions[name] = _normalize_version(raw, name)
    return versions


def _user_tool_state(bin_dir: Path) -> dict[str, dict[str, str]]:
    """Collect installed user tools (herdr) declared in the contract."""
    contract = load_contract()
    declared = contract.get("user_tools", {})
    state: dict[str, dict[str, str]] = {}
    for name, spec in declared.items():
        if not _applies_to_current_os(spec):
            continue
        binary = shutil.which(name) or str(bin_dir / name)
        raw = _run_version(Path(binary), "--version")
        normalized = _normalize_version(raw, name)
        entry: dict[str, str] = {
            "declared_version": spec.get("version", "unknown"),
            "installed_version": normalized,
            "raw": raw,
            "path": binary,
        }
        path = Path(binary)
        if path.exists() and not path.is_symlink():
            entry["sha256"] = sha256_file(path)
        state[name] = entry
    return state


def _desktop_entry_state(applications_dir: Path) -> dict[str, dict[str, str]]:
    """Collect the SHA-256 of each declared desktop entry's installed file."""
    contract = load_contract()
    declared = contract.get("desktop_entries", {})
    state: dict[str, dict[str, str]] = {}
    for name, spec in declared.items():
        if not _applies_to_current_os(spec):
            continue
        target = applications_dir / f"{name}.desktop"
        entry: dict[str, str] = {"path": str(target), "present": str(target.exists())}
        if target.exists() and target.is_file():
            entry["sha256"] = sha256_file(target)
        state[name] = entry
    return state


def collect_state(*, home: Path) -> dict[str, Any]:
    """Build the full device state dict from the live machine."""
    bin_dir = home / ".local/bin"
    share_rldyour = home / ".local/share/rldyour"
    applications_dir = home / ".local/share/applications"

    # On a fresh machine before bootstrap, ~/.local/bin may not exist yet.
    # safe_directory would treat that as a missing required path and fail;
    # tolerate absence so build can snapshot an all-absent device.
    if bin_dir.exists():
        safe_directory(bin_dir, enforce_private_mode=False)
    if share_rldyour.exists():
        safe_directory(share_rldyour, enforce_private_mode=False)
    if applications_dir.exists():
        safe_directory(applications_dir, enforce_private_mode=False)

    return {
        "schema": SCHEMA,
        "owner": OWNER,
        "bootstrap_version": BOOTSTRAP_VERSION,
        "home": str(home),
        "platform": f"{os.uname().sysname}-{os.uname().machine}",
        "policy_hashes": policy_hashes(),
        "runtime_hosts": _runtime_versions(bin_dir),
        "pinned_source_tools": _pinned_source_tool_versions(bin_dir),
        "user_tools": _user_tool_state(bin_dir),
        "desktop_entries": _desktop_entry_state(applications_dir),
    }


# ----------------------------- receipt integrity -----------------------------


def payload_with_integrity(state: dict[str, Any]) -> dict[str, Any]:
    result = dict(state)
    result["payload_sha256"] = sha256_bytes(canonical_bytes(state))
    return result


def load_receipt(path: Path, *, metadata_only: bool = False) -> dict[str, Any]:
    regular_owned(path)
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrityError(f"device receipt is invalid JSON: {path}") from exc
    if not isinstance(data, dict):
        fail("device receipt root must be an object")
    if raw != canonical_bytes(data):
        fail("device receipt is not canonical JSON")
    digest = data.get("payload_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        fail("device receipt integrity field is malformed")
    state = dict(data)
    state.pop("payload_sha256", None)
    if sha256_bytes(canonical_bytes(state)) != digest:
        fail("device receipt payload digest changed")
    if data.get("schema") != SCHEMA or data.get("owner") != OWNER:
        fail("device receipt ownership/schema is wrong")
    return data


def verify_receipt(path: Path) -> dict[str, Any]:
    """Verify the receipt matches the live device exactly.

    Two checks: (1) re-collect state and compare structurally to the stored
    receipt (a binary changed, a file vanished, a path moved); (2) compare
    every declared runtime/tool version against the contract (the installer and
    the contract must agree). Either failing is ``NOT_PROVEN``.
    """
    data = load_receipt(path)
    if data.get("bootstrap_version") != BOOTSTRAP_VERSION:
        fail("device receipt belongs to a different bootstrap version")
    expected_home = Path.home()
    if data.get("home") != str(expected_home):
        fail("device receipt belongs to a different home directory")
    actual = collect_state(home=expected_home)
    expected = dict(data)
    expected.pop("payload_sha256", None)
    if actual != expected:
        fail("installed device runtime differs from its exact receipt")
    _verify_contract_versions(actual)
    return data


def _verify_contract_versions(state: dict[str, Any]) -> None:
    """Assert every installed runtime/tool version matches the contract.

    This closes the gap that ``ubuntu/verify.sh`` leaves open: that script
    compares against literals hardcoded in bash, which can drift from the
    contract. Here the contract is the single source of truth.
    """
    contract = load_contract()
    runtime_support = contract.get("runtime_support", {})
    drifts: list[str] = []

    for name, _flag, field in [
        (n, RUNTIME_HOSTS[n][0], RUNTIME_HOSTS[n][1]) for n in RUNTIME_HOSTS
    ]:
        declared = runtime_support.get(field)
        if declared is None:
            continue
        installed = state.get("runtime_hosts", {}).get(name, {}).get("normalized")
        # Strip a leading 'v' from the declared value: the contract stores
        # "v0.23.0" for gopls (matching the Go module tag), but the installed
        # binary reports "0.23.0" (semver without the Go-module prefix).
        declared_norm = declared.lstrip("v") if declared else declared
        if installed is None or installed == "absent":
            drifts.append(f"{name}: absent (contract declares {declared})")
        elif installed != declared_norm:
            drifts.append(f"{name}: installed {installed} != contract {declared}")

    declared_tools = runtime_support.get(PINNED_SOURCE_TOOLS_CONTRACT, {})
    installed_tools = state.get("pinned_source_tools", {})
    for name, spec in declared_tools.items():
        declared = spec.get("version")
        installed = installed_tools.get(name)
        if installed is None:
            drifts.append(f"{name}: absent (contract declares {declared})")
        elif installed != declared:
            drifts.append(f"{name}: installed {installed} != contract {declared}")

    declared_user_tools = contract.get("user_tools", {})
    installed_user_tools = state.get("user_tools", {})
    for name, spec in declared_user_tools.items():
        if not _applies_to_current_os(spec):
            continue
        declared = spec.get("version")
        installed = installed_user_tools.get(name, {}).get("installed_version")
        if installed is None or installed == "absent":
            drifts.append(f"{name}: absent (contract declares {declared})")
        elif installed != declared:
            drifts.append(f"{name}: installed {installed} != contract {declared}")

    if drifts:
        fail("device drifts from contract:\n  " + "\n  ".join(drifts))


# ----------------------------- CLI -----------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser(
        "build", help="build a receipt from the current device state"
    )
    build.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RECEIPT,
        help=f"receipt path (default: {DEFAULT_RECEIPT})",
    )

    verify = subparsers.add_parser(
        "verify", help="verify the device matches its receipt and the contract"
    )
    verify.add_argument("--receipt", type=Path)
    verify.add_argument("--json", action="store_true")

    metadata = subparsers.add_parser(
        "metadata-only",
        help="validate receipt ownership/canonical self-integrity before replacement",
    )
    metadata.add_argument("--receipt", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "build":
            output: Path = args.output
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists() or output.is_symlink():
                # build replaces a stale receipt: validate the old one's
                # metadata first, then atomically swap. This mirrors the
                # metadata-only gate the browser receipt uses before an
                # in-place replacement.
                if not _is_our_receipt(output):
                    fail(f"refusing to overwrite unmanaged receipt: {output}")
                backup = output.with_suffix(".json.bak")
                output.rename(backup)
            state = collect_state(home=Path.home())
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            descriptor = os.open(output, flags, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(canonical_bytes(payload_with_integrity(state)))
                    handle.flush()
                    os.fsync(handle.fileno())
            except BaseException:
                output.unlink(missing_ok=True)
                raise
            print(output)
            return 0

        if args.command == "metadata-only":
            load_receipt(args.receipt, metadata_only=True)
            print("device-receipt-metadata-ok")
            return 0

        receipt = args.receipt or DEFAULT_RECEIPT
        data = verify_receipt(receipt)
        result = {
            "status": "PROVEN",
            "receipt": str(receipt),
            "payload_sha256": data["payload_sha256"],
            "platform": data.get("platform", "unknown"),
        }
        if args.json:
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        else:
            print("device-integrity: PROVEN")
            print(f"receipt: {receipt}")
            print(f"platform: {data.get('platform', 'unknown')}")
        return 0
    except IntegrityError as exc:
        result = {"status": "NOT_PROVEN", "error": str(exc)}
        if getattr(args, "json", False):
            print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        else:
            print(f"device-integrity: NOT_PROVEN: {exc}", file=sys.stderr)
        return 1


def _is_our_receipt(path: Path) -> bool:
    """Return True if ``path`` is one of our receipts (correct schema/owner)."""
    try:
        data = json.loads(path.read_bytes())
        return (
            isinstance(data, dict)
            and data.get("schema") == SCHEMA
            and data.get("owner") == OWNER
        )
    except (OSError, json.JSONDecodeError):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
