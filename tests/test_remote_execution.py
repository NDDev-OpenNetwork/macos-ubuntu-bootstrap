"""Fail-closed source/LSP desktop to build-server handoff."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/remote-exec.sh"
CONTRACT = ROOT / "config/rldyour-contract.json"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True, check=False)


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


def test_remote_execution_has_no_eval_or_implicit_sync() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "eval " not in source
    assert "rsync" not in source
    assert "scp " not in source
    assert 'exec -- "$@"' in source
    assert '[ -d "$repo/.git" ]' not in source
    assert "rev-parse --is-inside-work-tree" in source
