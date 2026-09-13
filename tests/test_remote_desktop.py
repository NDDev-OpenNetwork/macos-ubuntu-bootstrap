from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts/bootstrap.sh"
CLIENT = ROOT / "scripts/remote-desktop-client.py"
SERVER = ROOT / "scripts/ubuntu/remote-desktop.sh"


def test_remote_desktop_contract_binds_server_and_client_boundaries() -> None:
    contract = json.loads((ROOT / "config/rldyour-contract.json").read_text(encoding="utf-8"))
    remote = contract["remote_desktop"]
    assert remote["profile"] == "desktop-server"
    assert remote["server_platform"] == {
        "os": "ubuntu", "release": "24.04", "architecture": "amd64",
    }
    assert (remote["rdp_bind"], remote["rdp_port"]) == ("127.0.0.1", 3389)
    assert remote["public_rdp_listener"] == "forbidden"
    assert remote["client_bundle_secrets"] == "forbidden"
    assert remote["default_ssh_ports"] == [22, 443]
    assert ROOT / remote["server_entrypoint"] == SERVER
    assert ROOT / remote["client_renderer"] == CLIENT


def _client_module():
    spec = importlib.util.spec_from_file_location("remote_desktop_client", CLIENT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _host_key(tmp_path: Path) -> Path:
    private = tmp_path / "host"
    completed = subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(private)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return private.with_suffix(".pub")


def test_desktop_server_plan_declares_loopback_rdp_and_owner_tunnel() -> None:
    completed = subprocess.run(
        [
            "bash", str(BOOTSTRAP), "--platform", "ubuntu", "--profile", "desktop-server",
            "--plan", "--skip-system", "--skip-ai", "--skip-lsps", "--skip-checks",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    output = completed.stdout + completed.stderr
    assert "127.0.0.1:3389" in output
    assert "require an SSH tunnel" in output


def test_server_module_has_no_public_rdp_listener_literal() -> None:
    source = SERVER.read_text(encoding="utf-8")
    assert "tcp://127.0.0.1:${RLDYOUR_RDP_PORT}" in source
    assert "0.0.0.0:3389" not in source
    assert "[::]:3389" not in source
    assert "AllowRootLogin=false" in source
    assert "--global mask gnome-remote-desktop.service" in source
    assert "trap \"rm -rf -- '$tmp'; trap - RETURN\" RETURN" in source
    assert "trap 'rm -rf -- \"$tmp\"' RETURN" not in source


def test_rdp_profiles_preserve_the_proven_amsterdam_client_shape() -> None:
    module = _client_module()
    normal = module.rdp_profile(13389, "desktop", False)
    slow = module.rdp_profile(13389, "desktop", True)
    common = {
        "full address:s:127.0.0.1:13389",
        "desktopwidth:i:1920",
        "desktopheight:i:1080",
        "session bpp:i:32",
        "dynamic resolution:i:0",
        "smart sizing:i:1",
        "authentication level:i:2",
        "redirectprinters:i:0",
    }
    assert common <= set(normal.splitlines())
    assert common <= set(slow.splitlines())
    assert "connection type:i:5" in normal
    assert "audiomode:i:0" in normal
    assert "connection type:i:2" in slow
    assert "audiomode:i:2" in slow


def test_client_bundle_is_credential_free_and_platform_native(tmp_path: Path) -> None:
    key = _host_key(tmp_path)
    output = tmp_path / "bundle"
    completed = subprocess.run(
        [
            sys.executable, str(CLIENT), "--host", "desktop.example.test",
            "--ssh-user", "operator", "--desktop-user", "desktop",
            "--host-key-file", str(key), "--ssh-port", "22", "--ssh-port", "443",
            "--out", str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert {path.name for path in output.iterdir()} == {
        "README.txt", "desktop-server.rdp", "desktop-server-slow-network.rdp",
        "install-macos-tunnel.sh", "install-windows-tunnel.ps1",
    }
    subprocess.run(["bash", "-n", str(output / "install-macos-tunnel.sh")], check=True)
    corpus = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
    assert "desktop.example.test" in corpus
    assert "StrictHostKeyChecking yes" in corpus
    assert "ForwardAgent no" in corpus
    assert "PasswordAuthentication no" in corpus
    assert "KbdInteractiveAuthentication no" in corpus
    assert 'ssh -p "$port"' in corpus
    assert "SSH authentication failed on every configured port" in corpus
    assert "Test-NetConnection -ComputerName 127.0.0.1" in corpus
    assert '/usr/bin/nc -z 127.0.0.1 "$local_port"' in corpus
    assert "BEGIN OPENSSH PRIVATE KEY" not in corpus
    assert "188.166." not in corpus
    assert "nddev-amsterdam" not in corpus


def test_client_renderer_refuses_invalid_identity_and_overwrite(tmp_path: Path) -> None:
    key = _host_key(tmp_path)
    output = tmp_path / "bundle"
    base = [
        sys.executable, str(CLIENT), "--host", "desktop.example.test",
        "--ssh-user", "operator", "--desktop-user", "desktop",
        "--host-key-file", str(key), "--out", str(output),
    ]
    assert subprocess.run(base, cwd=ROOT, check=False).returncode == 0
    second = subprocess.run(base, cwd=ROOT, text=True, capture_output=True, check=False)
    assert second.returncode != 0
    assert "output already exists; preserved" in second.stderr
    hostile = subprocess.run(
        [*base[:-2], "bad;host", *base[-2:]],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert hostile.returncode != 0


@pytest.mark.parametrize("user", ["root;touch", "-option", "name with space", "a" * 40])
def test_client_renderer_rejects_unsafe_users(user: str) -> None:
    module = _client_module()
    with pytest.raises(Exception):
        module.checked_user(user)
