# Ubuntu desktop-server

`desktop-server` turns an Ubuntu 24.04 amd64 host into a persistent remote GNOME
workstation without publishing RDP to the network. It is plan-first and must be
run as the existing desktop owner, never as root.

## Server boundary

- The profile composes the normal GUI workstation and full server baseline.
- Docker defaults to `none`; `--docker-mode rootful` and `rootless` remain
  explicit choices.
- The desktop account must already be a non-root login account below `/home`.
  Bootstrap does not create, read, print or store its password.
- XRDP and xorgxrdp come from the signed Ubuntu archive when absent. An already
  installed compatible version is preserved because apply uses `--no-upgrade`.
- XRDP uses TLS and listens only on `127.0.0.1:3389`. Root login is disabled,
  disconnected sessions persist, GNOME Remote Desktop is disabled, and the host
  boots to `multi-user.target` so a local display manager cannot compete for the
  remote session.
- No UFW rule exposes 3389. SSH is the only transport boundary.

Plan and, after operator review, apply:

```bash
bash scripts/bootstrap.sh --platform ubuntu --profile desktop-server
bash scripts/bootstrap.sh --platform ubuntu --profile desktop-server --docker-mode rootful
bash scripts/bootstrap.sh --platform ubuntu --profile desktop-server --apply
bash scripts/bootstrap.sh --platform ubuntu --profile desktop-server --docker-mode rootful --apply
```

The second command changes packages, systemd services and XRDP configuration.
Keep the current SSH session open until a second key-authenticated SSH session
and the RDP path have both been tested.

## Client bundle

The renderer accepts deployment facts at invocation time, so public source never
contains the server address, user names or a private key:

```bash
python3 scripts/remote-desktop-client.py \
  --host desktop.example.net \
  --ssh-user operator \
  --desktop-user operator \
  --host-key-file /etc/ssh/ssh_host_ed25519_key.pub \
  --ssh-port 22 --ssh-port 443 \
  --out /safe/operator-selected/path/desktop-client
```

Read the public host key locally on the server or through a separately trusted
channel. Do not obtain it from the first unverified connection. The output path
must not already exist; the renderer preserves existing data rather than
overwriting it.

On macOS, run `install-macos-tunnel.sh` as the logged-in user and import the RDP
file into Windows App. On Windows, run `install-windows-tunnel.ps1` as the
logged-in user and open the RDP file with Windows App or the built-in Remote
Desktop Connection client. Both installers:

1. require a pre-existing owner SSH private key;
2. pin the supplied Ed25519 server host key and disable password, interactive,
   agent-forwarding and host-key-update paths;
3. test SSH ports in the declared order, normally 22 then 443;
4. install a per-user reconnecting tunnel from `127.0.0.1:13389` to server
   `127.0.0.1:3389`;
5. wait for the local forwarded port before reporting success.

The normal RDP profile enables audio. The slow-network profile disables audio
and selects the low-bandwidth connection class. Neither file contains an RDP
password, SSH private key, or public server RDP endpoint.

## Verification and evidence

Server verification is read-only:

```bash
bash scripts/ubuntu/remote-desktop.sh --verify --user "$USER"
```

It checks the supported platform, required packages and services, owned XRDP
settings, the actual listening socket, and boot target. It fails if any RDP
listener is not exactly `127.0.0.1:3389`.

The current Amsterdam host supplies evidence that the predecessor runtime works
with XRDP 0.10 on loopback. It does not prove a clean bootstrap apply, repeat
apply, reboot recovery, or a newly generated Windows client. Those remain a
typed `REAL_HOST_REQUIRED` gap in the support evidence matrix.
