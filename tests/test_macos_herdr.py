import hashlib
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "scripts/macos/install.sh"


def _fixture_binary(path: Path, version: str = "0.8.0") -> str:
    path.write_text(f'#!/bin/sh\necho "herdr {version}"\n', encoding="utf-8")
    path.chmod(0o755)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_installer_function(
    home: Path,
    binary: Path,
    sha256: str,
    *,
    download_result: int = 0,
    machine: str = "arm64",
) -> subprocess.CompletedProcess[str]:
    script = r'''
source "$1"
HERDR_VERSION=0.8.0
HERDR_MACOS_AARCH64_SHA256="$2"
HERDR_MACOS_AARCH64_URL=https://github.com/herdrdev/herdr/releases/download/v0.8.0/herdr-macos-aarch64
rldyour::download_verified_file() {
  [ "$1" = "$HERDR_MACOS_AARCH64_URL" ] || return 91
  [ "$2" = "$HERDR_MACOS_AARCH64_SHA256" ] || return 92
  [ "$RLDYOUR_TEST_DOWNLOAD_RESULT" -eq 0 ] || return "$RLDYOUR_TEST_DOWNLOAD_RESULT"
  cp "$RLDYOUR_TEST_HERDR" "$3"
}
uname() {
  [ "$1" = -s ] && { printf '%s\n' Darwin; return; }
  [ "$1" = -m ] && { printf '%s\n' "$RLDYOUR_TEST_MACHINE"; return; }
  command uname "$@"
}
RLDYOUR_DRY_RUN=0
ensure_herdr
'''
    return subprocess.run(
        ["bash", "-c", script, "macos-herdr-test", str(INSTALL), sha256],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{home / '.local/bin'}{os.pathsep}{os.environ['PATH']}",
            "RLDYOUR_TEST_HERDR": str(binary),
            "RLDYOUR_TEST_DOWNLOAD_RESULT": str(download_result),
            "RLDYOUR_TEST_MACHINE": machine,
        },
    )


def test_macos_herdr_is_receipt_bound_and_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    binary = tmp_path / "herdr-fixture"
    sha256 = _fixture_binary(binary)

    first = _run_installer_function(home, binary, sha256)
    assert first.returncode == 0, first.stderr + first.stdout
    target = home / ".local/share/rldyour/herdr/0.8.0/herdr"
    receipt = target.parent / ".receipt"
    launcher = home / ".local/bin/herdr"
    assert target.read_bytes() == binary.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o755
    assert launcher.is_symlink()
    assert launcher.readlink() == target
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert receipt.read_text(encoding="utf-8") == (
        "# Managed by macos-ubuntu-bootstrap: macos-herdr-runtime-v1\n"
        "version=0.8.0\n"
        f"sha256={sha256}\n"
        "source=https://github.com/herdrdev/herdr/releases/download/v0.8.0/herdr-macos-aarch64\n"
    )

    inode = target.stat().st_ino
    second = _run_installer_function(home, binary, sha256)
    assert second.returncode == 0, second.stderr + second.stdout
    assert target.stat().st_ino == inode


def test_macos_herdr_preserves_divergent_managed_target(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    binary = tmp_path / "herdr-fixture"
    sha256 = _fixture_binary(binary)
    assert _run_installer_function(home, binary, sha256).returncode == 0
    target = home / ".local/share/rldyour/herdr/0.8.0/herdr"
    target.write_bytes(b"tampered\n")

    result = _run_installer_function(home, binary, sha256)
    assert result.returncode != 0
    assert target.read_bytes() == b"tampered\n"
    assert "checksum diverged; preserved" in result.stderr + result.stdout


def test_macos_herdr_preserves_unmanaged_launcher(tmp_path: Path) -> None:
    home = tmp_path / "home"
    launcher = home / ".local/bin/herdr"
    launcher.parent.mkdir(parents=True)
    launcher.write_bytes(b"unmanaged\n")
    binary = tmp_path / "herdr-fixture"
    sha256 = _fixture_binary(binary)

    result = _run_installer_function(home, binary, sha256)
    assert result.returncode != 0
    assert launcher.read_bytes() == b"unmanaged\n"
    assert "unmanaged Herdr launcher exists; preserved" in result.stderr + result.stdout


def test_macos_herdr_wrong_hash_fails_before_publication(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    binary = tmp_path / "herdr-fixture"
    _fixture_binary(binary)
    wrong_hash = "0" * 64

    result = _run_installer_function(home, binary, wrong_hash)
    assert result.returncode != 0
    assert not (home / ".local/share/rldyour/herdr/0.8.0").exists()
    assert "checksum diverged before publication" in result.stderr + result.stdout


def test_macos_herdr_wrong_reported_version_fails_before_publication(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    binary = tmp_path / "herdr-fixture"
    sha256 = _fixture_binary(binary, version="0.7.5")

    result = _run_installer_function(home, binary, sha256)
    assert result.returncode != 0
    assert not (home / ".local/share/rldyour/herdr/0.8.0").exists()
    assert "reports 0.7.5, expected 0.8.0" in result.stderr + result.stdout


def test_macos_herdr_unavailable_asset_fails_without_partial_root(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    binary = tmp_path / "herdr-fixture"
    sha256 = _fixture_binary(binary)

    result = _run_installer_function(home, binary, sha256, download_result=22)
    assert result.returncode != 0
    assert not (home / ".local/share/rldyour/herdr/0.8.0").exists()
    assert "asset is unavailable or failed checksum verification" in result.stderr + result.stdout


def test_macos_herdr_unsupported_architecture_fails_before_download(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    binary = tmp_path / "herdr-fixture"
    sha256 = _fixture_binary(binary)

    result = _run_installer_function(home, binary, sha256, machine="x86_64")
    assert result.returncode != 0
    assert not (home / ".local/share/rldyour/herdr/0.8.0").exists()
    assert "no managed macOS artifact for Darwin/x86_64" in result.stderr + result.stdout


def test_macos_herdr_partial_receipt_fails_closed_without_repair(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = home / ".local/share/rldyour/herdr/0.8.0"
    root.mkdir(parents=True)
    binary = tmp_path / "herdr-fixture"
    sha256 = _fixture_binary(binary)
    target = root / "herdr"
    target.write_bytes(binary.read_bytes())
    target.chmod(0o755)
    receipt = root / ".receipt"
    receipt.write_text(
        "# Managed by macos-ubuntu-bootstrap: macos-herdr-runtime-v1\nversion=0.8.0\n",
        encoding="utf-8",
    )
    receipt.chmod(0o600)
    before = receipt.read_bytes()

    result = _run_installer_function(home, binary, sha256)
    assert result.returncode != 0
    assert receipt.read_bytes() == before
    assert target.read_bytes() == binary.read_bytes()
    assert "receipt is missing or divergent; preserved" in result.stderr + result.stdout


def test_macos_herdr_divergent_permissions_fail_closed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    binary = tmp_path / "herdr-fixture"
    sha256 = _fixture_binary(binary)
    assert _run_installer_function(home, binary, sha256).returncode == 0
    target = home / ".local/share/rldyour/herdr/0.8.0/herdr"
    target.chmod(0o775)

    result = _run_installer_function(home, binary, sha256)
    assert result.returncode != 0
    assert target.stat().st_mode & 0o777 == 0o775
    assert "permissions diverged; preserved" in result.stderr + result.stdout


def test_macos_herdr_additional_managed_root_path_fails_closed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    binary = tmp_path / "herdr-fixture"
    sha256 = _fixture_binary(binary)
    assert _run_installer_function(home, binary, sha256).returncode == 0
    root = home / ".local/share/rldyour/herdr/0.8.0"
    extra = root / "unexpected"
    extra.write_bytes(b"preserve me\n")

    result = _run_installer_function(home, binary, sha256)
    assert result.returncode != 0
    assert extra.read_bytes() == b"preserve me\n"
    assert "missing or additional paths; preserved" in result.stderr + result.stdout
