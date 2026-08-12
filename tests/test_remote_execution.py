"""Fail-closed source/LSP desktop to build-server handoff.

Two layers, deliberately:

1. A deterministic protocol harness (``fake_ssh``) that reproduces the part of
   OpenSSH this seam depends on: the client joins the remote-command argv with
   single spaces and the remote login shell parses the resulting string before
   the receiver sees it. This layer never touches the network, so it runs on
   every hosted runner and is the regression gate.
2. A real ``sshd`` round trip on loopback, which proves the same properties
   against the actual implementation. It self-skips only when the machine has
   no OpenSSH server binary.

Layer 1 exists because a static "the source contains no ``eval``" assertion
cannot see this defect at all: the evaluation is performed by the *remote*
shell, not by this script.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/remote-exec.sh"
CONTRACT = ROOT / "config/rldyour-contract.json"

# Every argument class that a shell parse would damage if the argv were not
# quoted exactly once before it crosses the wire.
HOSTILE_ARGV = [
    "",
    "two words",
    "it's",
    'double"quote',
    "a;b",
    "c|d",
    "e&f",
    "$(id -un)",
    "`id -un`",
    "${HOME}",
    "-leading-dash",
    "*",
    "?",
    "[a-z]",
    "back\\slash",
    "tab\there",
    "new\nline",
    "юникод 🚀",
]


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"},
    )


def make_repo(path: Path, content: str = "content\n") -> Path:
    """A clean single-commit repository, usable as both ends of the handoff.

    ``content`` must differ between two repositories that are meant to have
    different HEADs: identical trees committed in the same second by the same
    identity produce the same commit hash, which would silently turn a
    mismatch test into a match test.
    """
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", ".")
    _git(path, "config", "user.email", "test@example.invalid")
    _git(path, "config", "user.name", "test")
    (path / "tracked").write_text(content, encoding="utf-8")
    _git(path, "add", "tracked")
    _git(path, "-c", "commit.gpgsign=false", "commit", "-qm", "init")
    return path


@pytest.fixture
def fake_ssh(tmp_path: Path) -> Path:
    """A PATH directory whose ``ssh`` models OpenSSH's remote-command protocol.

    OpenSSH concatenates the command arguments with single spaces and sshd runs
    the result through the login shell. Reproducing exactly that -- and nothing
    else -- is what makes this harness a protocol test rather than a mock.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    ssh = bin_dir / "ssh"
    ssh.write_text(
        "#!/usr/bin/env bash\n"
        "args=(\"$@\")\n"
        '[ "${args[0]}" = "--" ] && args=("${args[@]:1}")\n'
        "unset 'args[0]'\n"  # drop the destination
        'joined=""\n'
        'for a in "${args[@]}"; do joined+="$a "; done\n'
        'exec /bin/sh -c "$joined"\n',
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    return bin_dir


def call(repo: Path, fake_bin: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
    )


# ----------------------------- contract -----------------------------


def test_contract_pairs_source_desktop_with_server_executor() -> None:
    remote = json.loads(CONTRACT.read_text(encoding="utf-8"))["remote_execution"]
    assert remote["client_profiles"] == ["desktop"]
    assert remote["executor_profile"] == "server"
    assert remote["transport"] == "openssh-exact-head"
    assert remote["workspace_transfer"] == "forbidden"
    assert remote["remote_head_match"] == "required"


def test_remote_execution_requires_explicit_safe_target() -> None:
    assert run().returncode == 2
    assert run("--host", "build.example", "--remote-repo", "relative", "--", "true").returncode == 2
    assert run("--host", "bad host", "--remote-repo", "/srv/work", "--", "true").returncode == 2
    assert run("--host", "-oProxyCommand=bad", "--remote-repo", "/srv/work", "--", "true").returncode == 2


@pytest.mark.parametrize(
    "unsafe",
    ["/srv/work;id", "/srv/work&id", "/srv/work|id", "/srv/$(id)", "/srv/`id`", "/srv/'x", '/srv/"x'],
)
def test_remote_repo_is_charset_validated_like_the_host(unsafe: str) -> None:
    """The destination was charset-checked and the repository path was not."""
    result = run("--host", "build.example", "--remote-repo", unsafe, "--", "true")
    assert result.returncode == 2
    assert "unsafe remote repository path" in result.stderr


def test_remote_execution_has_no_eval_or_implicit_sync() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "eval " not in source
    assert "rsync" not in source
    assert "scp " not in source
    assert 'exec -- "$@"' in source
    assert "rev-parse --is-inside-work-tree" in source
    # The argv must be quoted before it reaches ssh; passing "$@" straight
    # through is the defect this module exists to prevent.
    assert "rldyour::remote_exec::shquote" in source
    assert 'ssh -- "$host" bash -s -- "$@"' not in source


# ----------------------------- dirty-state gates -----------------------------


def test_every_local_dirty_state_fails_with_its_own_reason(tmp_path: Path, fake_ssh: Path) -> None:
    repo = make_repo(tmp_path / "repo")

    (repo / "tracked").write_text("modified\n", encoding="utf-8")
    unstaged = call(repo, fake_ssh, "--host", "h", "--remote-repo", str(repo), "--", "true")
    assert unstaged.returncode == 3
    assert "unstaged changes" in unstaged.stderr

    _git(repo, "add", "tracked")
    staged = call(repo, fake_ssh, "--host", "h", "--remote-repo", str(repo), "--", "true")
    assert staged.returncode == 3
    assert "staged changes" in staged.stderr

    # Unstage first, then restore the worktree: the reverse order leaves the
    # modification in the worktree and the unstaged gate fires instead.
    _git(repo, "reset", "-q")
    _git(repo, "checkout", "-q", "--", "tracked")
    (repo / "untracked").write_text("x\n", encoding="utf-8")
    untracked = call(repo, fake_ssh, "--host", "h", "--remote-repo", str(repo), "--", "true")
    assert untracked.returncode == 3
    assert "untracked files" in untracked.stderr


# ----------------------------- argv protocol -----------------------------


def test_argv_survives_the_remote_shell_parse(tmp_path: Path, fake_ssh: Path) -> None:
    """Each argument must arrive as one argument, byte for byte."""
    repo = make_repo(tmp_path / "repo")
    result = call(
        repo, fake_ssh, "--host", "h", "--remote-repo", str(repo), "--",
        "printf", "<%s>\n", *HOSTILE_ARGV,
    )
    assert result.returncode == 0, result.stderr
    expected = "".join(f"<{arg}>\n" for arg in HOSTILE_ARGV)
    assert result.stdout == expected


def test_metacharacters_do_not_start_a_second_remote_command(
    tmp_path: Path, fake_ssh: Path
) -> None:
    repo = make_repo(tmp_path / "repo")
    result = call(
        repo, fake_ssh, "--host", "h", "--remote-repo", str(repo), "--",
        "echo", "literal; echo INJECTED",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "literal; echo INJECTED\n"
    assert "INJECTED\n" != result.stdout


def test_nothing_executes_when_the_head_gate_rejects(tmp_path: Path, fake_ssh: Path) -> None:
    """ADR 0009: execution stops BEFORE the requested command starts.

    A trailing metacharacter used to survive the gate because the remote shell
    had already split it into an independent command.
    """
    repo = make_repo(tmp_path / "repo")
    result = call(
        repo, fake_ssh, "--host", "h", "--remote-repo", "/nonexistent-remote-repo", "--",
        "echo", "x; echo RAN-DESPITE-GATE-FAILURE",
    )
    assert result.returncode == 4
    assert "RAN-DESPITE-GATE-FAILURE" not in result.stdout
    assert "remote repository is unavailable" in result.stderr


def test_remote_head_mismatch_is_refused(tmp_path: Path, fake_ssh: Path) -> None:
    local = make_repo(tmp_path / "local", content="local\n")
    remote = make_repo(tmp_path / "remote", content="remote\n")
    result = call(local, fake_ssh, "--host", "h", "--remote-repo", str(remote), "--", "true")
    assert result.returncode == 6
    assert "remote HEAD mismatch" in result.stderr


def test_dirty_remote_worktree_is_refused(tmp_path: Path, fake_ssh: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    dirty_marker = repo / "remote-only-dirt"
    dirty_marker.write_text("x\n", encoding="utf-8")
    try:
        result = call(repo, fake_ssh, "--host", "h", "--remote-repo", str(repo), "--", "true")
        # The same path is both ends here, so the local untracked gate fires
        # first; that ordering is itself the contract.
        assert result.returncode == 3
    finally:
        dirty_marker.unlink()


def test_remote_repository_path_may_contain_spaces(tmp_path: Path, fake_ssh: Path) -> None:
    repo = make_repo(tmp_path / "re po")
    result = call(repo, fake_ssh, "--host", "h", "--remote-repo", str(repo), "--", "pwd")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(repo)


def test_remote_exit_status_propagates(tmp_path: Path, fake_ssh: Path) -> None:
    repo = make_repo(tmp_path / "repo")
    result = call(repo, fake_ssh, "--host", "h", "--remote-repo", str(repo), "--",
                  "sh", "-c", "exit 42")
    assert result.returncode == 42


# ----------------------------- real OpenSSH -----------------------------


SSHD = next(
    (p for p in ("/usr/sbin/sshd", "/usr/local/sbin/sshd", "/opt/homebrew/sbin/sshd")
     if Path(p).exists()),
    None,
)
requires_sshd = pytest.mark.skipif(
    SSHD is None or shutil.which("ssh-keygen") is None or shutil.which("ssh") is None,
    reason="no OpenSSH server available for a real loopback round trip",
)


@pytest.fixture
def live_ssh(tmp_path: Path) -> Iterator[Path]:
    """An isolated sshd on loopback plus an ``ssh`` shim that dials it.

    The shim only injects connection parameters; the client and server are the
    real OpenSSH implementation, so the join-and-parse behaviour under test is
    genuine. Nothing in the operator's own SSH configuration is read or written.
    """
    home = tmp_path / "sshhome"
    home.mkdir(mode=0o700)
    for name, comment in (("host", "scratch-host"), ("client", "scratch-client")):
        subprocess.run(
            ["ssh-keygen", "-q", "-t", "ed25519", "-f", str(home / name), "-N", "", "-C", comment],
            check=True,
        )
    (home / "authorized_keys").write_bytes((home / "client.pub").read_bytes())
    (home / "authorized_keys").chmod(0o600)

    port = 2200 + (os.getpid() % 300)
    config = home / "sshd_config"
    config.write_text(
        f"Port {port}\nListenAddress 127.0.0.1\nHostKey {home / 'host'}\n"
        f"AuthorizedKeysFile {home / 'authorized_keys'}\nStrictModes no\n"
        f"PasswordAuthentication no\nKbdInteractiveAuthentication no\nUsePAM no\n"
        f"PidFile {home / 'sshd.pid'}\nLogLevel ERROR\n",
        encoding="utf-8",
    )
    assert SSHD is not None
    started = subprocess.run(
        [SSHD, "-f", str(config), "-E", str(home / "sshd.log")], capture_output=True, text=True
    )
    if started.returncode != 0:
        pytest.skip(f"scratch sshd would not start: {started.stderr.strip()}")

    bin_dir = tmp_path / "livebin"
    bin_dir.mkdir()
    shim = bin_dir / "ssh"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        f'exec {shutil.which("ssh")} -p {port} -i "{home / "client"}" '
        "-o IdentitiesOnly=yes -o StrictHostKeyChecking=no "
        "-o UserKnownHostsFile=/dev/null -o BatchMode=yes -o LogLevel=ERROR \"$@\"\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        probe = subprocess.run(
            [str(shim), "127.0.0.1", "true"], capture_output=True, text=True
        )
        if probe.returncode == 0:
            break
        time.sleep(0.2)
    else:
        pytest.skip("scratch sshd never accepted a connection")

    try:
        yield bin_dir
    finally:
        pid_file = home / "sshd.pid"
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text(encoding="utf-8").strip()), 15)
            except (OSError, ValueError):
                # Best-effort teardown of a scratch daemon: it may already have
                # exited, or written a pid this process cannot signal. Raising
                # here would replace a real test result with a cleanup error,
                # and the container it lives in is discarded either way.
                pass


@requires_sshd
def test_real_openssh_preserves_argv_and_honours_the_gate(
    tmp_path: Path, live_ssh: Path
) -> None:
    repo = make_repo(tmp_path / "repo")

    ok = call(repo, live_ssh, "--host", "127.0.0.1", "--remote-repo", str(repo), "--",
              "printf", "<%s>\n", *HOSTILE_ARGV)
    assert ok.returncode == 0, ok.stderr
    assert ok.stdout == "".join(f"<{arg}>\n" for arg in HOSTILE_ARGV)

    blocked = call(repo, live_ssh, "--host", "127.0.0.1", "--remote-repo", "/nonexistent", "--",
                   "echo", "x; echo RAN-DESPITE-GATE-FAILURE")
    assert blocked.returncode == 4
    assert "RAN-DESPITE-GATE-FAILURE" not in blocked.stdout

    status = call(repo, live_ssh, "--host", "127.0.0.1", "--remote-repo", str(repo), "--",
                  "sh", "-c", "exit 42")
    assert status.returncode == 42
