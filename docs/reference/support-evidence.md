# Clean-system support and evidence

The canonical machine-readable boundary is
[`config/support-evidence-matrix.json`](../../config/support-evidence-matrix.json).
This page explains its vocabulary; it does not redefine the matrix.
The main contract references that file explicitly. `device_integrity.py` reports
the state of one installed device and therefore remains an observation format,
not a second platform-support policy source.

## Support versus proof

- `SUPPORTED` is a product contract for a clean-system composition.
- `UNSUPPORTED_FAIL_CLOSED` is an incompatible composition that the installer
  rejects before mutation.
- `UNSUPPORTED` is outside the product contract but does not claim a particular
  pre-mutation proof.
- `REQUIRED` capabilities must be `PROVEN` for a successful evidence lane.
- `OPTIONAL` capabilities may be `NOT_PROVEN` only with an explicit stronger
  required tier and tracking issue.

Evidence tiers are deliberately non-interchangeable:

| Tier | What it establishes |
|---|---|
| `HOSTED_NATIVE` | Apply and verification on a fresh GitHub-hosted VM of the declared OS/architecture |
| `DISPOSABLE_SYSTEMD_CONTAINER` | Real package/systemd logic inside a privileged disposable container, not a VM or bare-metal boundary |
| `STRUCTURAL` | Static/contract behavior without runtime proof |
| `EXPECTED_FAIL_CLOSED` | An unsupported combination was rejected before mutation |
| `REAL_HOST_REQUIRED` | Capability cannot be honestly established by the current hosted lane |

The current workflow produces exactly 26 artifacts, one for every declared
`(lane, release, architecture)` expansion. It natively covers macOS Apple
Silicon GUI/no-GUI installation, Ubuntu 24.04 and 26.04 amd64/arm64 desktop
no-GUI installation, Ubuntu ARM64 GUI refusal before mutation, and native
Ubuntu ARM64 rootless Docker on both releases. Every disposable systemd lane
runs separately for Ubuntu 24.04 and 26.04, so one release can
never stand in for the other.

Separate accepted real-host evidence proves Ubuntu 26.04 amd64 server
plan/apply/idempotency, Bun and tool baselines, systemd recovery after reboot,
preserved and second key-authenticated SSH, root rejection, external SSH/UFW,
Fail2ban, rootful Docker and the Docker-published-port/UFW boundary. Those
server facts are no longer `NOT_PROVEN` merely because they are outside the
hosted artifact set.

The remaining typed gaps are narrower: a disposable Ubuntu 26.04 Desktop with a
logged-in GNOME session and real PolicyKit agent; a reboot-capable disposable
macOS host for launchd/GUI recovery.
The exact remaining proof and tracking issue for each gap lives in
`known_evidence_gaps`; prose must not broaden an already accepted boundary.

## Authoritative platform boundaries

Facts were rechecked on 2026-08-28:

- [GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
  lists standard public `ubuntu-24.04`, `ubuntu-24.04-arm`, and ARM64
  `macos-15` runners. `ubuntu-26.04` and `ubuntu-26.04-arm` remain public
  preview; the workflow runs them as explicitly labelled supplementary native
  evidence and records `public-preview` in each artifact. Hosted Linux and
  macOS VMs use passwordless sudo, so they
  cannot prove ordinary password or PolicyKit prompt behavior.
- [Ubuntu supported architectures](https://documentation.ubuntu.com/project/how-ubuntu-is-made/concepts/supported-architectures/)
  includes amd64 and arm64. Vendor application artifacts impose the narrower
  Ubuntu GUI boundary recorded by this repository.
- [Ubuntu Server requirements](https://documentation.ubuntu.com/server/reference/installation/system-requirements/)
  lists both amd64 and arm64 server targets.
- [polkit architecture](https://polkit.pages.freedesktop.org/polkit/polkit.8.html)
  explains that graphical sessions normally provide authentication agents and
  SSH/headless sessions may not. The
  [pkexec manual](https://polkit.pages.freedesktop.org/polkit/pkexec.1.html)
  also documents its constrained environment and refusal/dismissal statuses.
- [Docker rootless mode](https://docs.docker.com/engine/security/rootless/)
  runs daemon and containers without root, but does not remove the installer’s
  separate need for authority to install system packages.

The generic reusable workflows provide lint, security, dependency, language,
and release tiers. Bootstrap platform semantics remain owned by this
repository’s exact-head `platform-evidence` workflow and must never be inferred
from a generic smoke check.
