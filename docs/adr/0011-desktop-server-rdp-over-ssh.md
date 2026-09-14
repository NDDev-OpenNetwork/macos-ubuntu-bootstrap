# ADR 0011: Keep desktop-server RDP behind an owner-managed SSH tunnel

## Status

Accepted — 2026-09-13.

## Context

The Amsterdam deployment needs a persistent Ubuntu graphical workstation that
can be reached from macOS and Windows. The existing deployment already proves a
GNOME-on-Xorg XRDP session through a local SSH forward. Publishing TCP 3389 or
embedding connection credentials in a public bootstrap would create a larger
and poorly owned authentication boundary.

Ubuntu 26.04 no longer provides the Xorg GNOME composition this implementation
depends on. The portable product boundary must therefore be narrower than the
other Ubuntu profiles.

## Decision

Add `desktop-server` for Ubuntu 24.04 amd64 only. It composes the desktop GUI and
server baselines, defaults Docker to `none`, and owns XRDP configuration but no
user or SSH credentials.

XRDP binds exclusively to `127.0.0.1:3389`. A deployment-time renderer creates
credential-free, per-user macOS and Windows client installers. Those installers
pin a deployment-supplied Ed25519 SSH host key and maintain a local OpenSSH
forward, normally `127.0.0.1:13389` to the server loopback listener. Ports 22
and 443 are transport alternatives, not separate trust paths.

Fresh installs use signed Ubuntu archive packages and do not upgrade an already
healthy XRDP installation implicitly. This preserves the deployed Amsterdam
0.10 packages without pretending that equivalent public release artifacts are
available from this repository.

## Consequences

- There is no public RDP listener or firewall exception.
- Passwords and private keys remain owner-managed and outside generated bundles.
- Ubuntu 26.04, ARM64, root execution, and GUI-disabled desktop-server tuples
  fail before mutation.
- Static and current-host checks cannot promote clean apply, idempotency, reboot
  recovery or cross-platform connection behavior to proven. Those require a
  disposable real-host evidence run.
