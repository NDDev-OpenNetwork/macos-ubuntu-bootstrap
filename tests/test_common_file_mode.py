import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "scripts/lib/common.sh"


def _run_file_mode(
    path: Path,
    *,
    kernel: str,
    kernel_status: int = 0,
    stat_output: str = "755",
    stat_status: int = 0,
) -> subprocess.CompletedProcess[str]:
    script = r'''
source "$1"
rldyour::_kernel_name() {
  printf '%s\n' "$RLDYOUR_TEST_KERNEL"
  return "$RLDYOUR_TEST_KERNEL_STATUS"
}
stat() {
  printf '%s\0' "$@" >"$RLDYOUR_TEST_STAT_ARGS"
  printf '%s\n' "$RLDYOUR_TEST_STAT_OUTPUT"
  return "$RLDYOUR_TEST_STAT_STATUS"
}
rldyour::file_mode "$2"
'''
    args_file = path.parent / "stat-args"
    result = subprocess.run(
        ["bash", "-c", script, "file-mode-test", str(COMMON), str(path)],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "RLDYOUR_TEST_KERNEL": kernel,
            "RLDYOUR_TEST_KERNEL_STATUS": str(kernel_status),
            "RLDYOUR_TEST_STAT_ARGS": str(args_file),
            "RLDYOUR_TEST_STAT_OUTPUT": stat_output,
            "RLDYOUR_TEST_STAT_STATUS": str(stat_status),
        },
    )
    result.stat_args = (
        args_file.read_bytes().rstrip(b"\0").decode().split("\0")
        if args_file.exists()
        else []
    )
    return result


def test_file_mode_selects_gnu_stat_and_normalizes_octal(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"payload")
    result = _run_file_mode(target, kernel="Linux", stat_output="0755")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "755\n"
    assert result.stat_args == ["-c", "%a", "--", str(target)]


def test_file_mode_selects_bsd_stat_explicitly(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"payload")
    result = _run_file_mode(target, kernel="Darwin", stat_output="600")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "600\n"
    assert result.stat_args == ["-f", "%Lp", str(target)]


def test_file_mode_fails_closed_on_unknown_kernel(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"payload")
    result = _run_file_mode(target, kernel="FreeBSD")
    assert result.returncode != 0
    assert result.stat_args == []
    assert "unsupported host kernel" in result.stderr


def test_file_mode_fails_closed_when_kernel_probe_fails(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"payload")
    result = _run_file_mode(target, kernel="Linux", kernel_status=9)
    assert result.returncode != 0
    assert result.stat_args == []
    assert "could not determine host kernel" in result.stderr


def test_file_mode_fails_closed_on_malformed_output(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"payload")
    result = _run_file_mode(target, kernel="Linux", stat_output="rwxr-xr-x")
    assert result.returncode != 0
    assert "malformed permission mode" in result.stderr


def test_file_mode_fails_closed_when_stat_fails(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"payload")
    result = _run_file_mode(target, kernel="Darwin", stat_status=7)
    assert result.returncode != 0
    assert "BSD stat failed" in result.stderr


def test_file_mode_fails_closed_when_gnu_stat_is_unavailable(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"payload")
    result = _run_file_mode(target, kernel="Linux", stat_status=127)
    assert result.returncode != 0
    assert "GNU stat failed" in result.stderr


def test_file_mode_fails_closed_before_stat_for_missing_path(tmp_path: Path) -> None:
    target = tmp_path / "missing"
    result = _run_file_mode(target, kernel="Linux")
    assert result.returncode != 0
    assert result.stat_args == []
    assert "missing path" in result.stderr
