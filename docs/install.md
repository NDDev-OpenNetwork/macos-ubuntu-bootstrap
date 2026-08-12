# Installation guide

Run `scripts/bootstrap.sh`; platform installers are internal composition layers.
Plan mode is the default and Ubuntu always requires an explicit profile.

```bash
bash scripts/bootstrap.sh --platform macos [--no-gui] [--apply]
bash scripts/bootstrap.sh --platform ubuntu --profile desktop [--no-gui] [--apply]
bash scripts/bootstrap.sh --platform ubuntu --profile desktop-builds [--no-gui] [--apply]
bash scripts/bootstrap.sh --platform ubuntu --profile server [--apply]
```

`desktop` provisions editing, LSPs, scanners, formatters, terminal tooling, and
local static checks without Docker. `desktop-builds` adds rootful Docker for
local builds/tests. `server` configures a headless Docker server and keeps risky
network hardening behind explicit flags.

Every profile installs official Codex, Claude Code, and Grok Build distributions
through verified downloads. `cx`, `cl`, and `gk` launch them without approval or
permission prompts. Authentication is performed afterward with
`scripts/auth-handoff.sh` and is never automated by bootstrap.

Herdr is a required terminal tool on macOS and every Ubuntu profile. macOS uses
the official Homebrew formula; Ubuntu installs the pinned x86_64/aarch64 binary
from the `herdrdev/herdr` GitHub release and verifies its runtime receipt.

GUI profiles install current Google Chrome stable. macOS also installs the
desktop applications listed in the contract. Ubuntu GUI installs RustDesk and
Telegram, configures GNOME, and removes Firefox. `--no-gui` retains command-line
tools, Herdr, language servers, and source checks.

Ubuntu Telegram Desktop is pinned to the official `telegramdesktop/tdesktop`
GitHub Linux tarball. That upstream release currently provides Linux x86_64 but
not Linux ARM64; Google Chrome has the same architecture boundary. Ubuntu ARM64
therefore supports `--no-gui` profiles only, and a real ARM64 GUI apply fails
before changing the host rather than claiming a partial GUI installation.

Server hardening is explicit:

```bash
bash scripts/bootstrap.sh --platform ubuntu --profile server --apply \
  --harden-ssh --enable-ufw --with-fail2ban
```

Keep the current SSH session open until a second key-authenticated connection
succeeds. UFW alone does not contain Docker-published ports.

Validate changes with `bash scripts/ci/lint.sh`, `bash scripts/ci/validate.sh`,
and `python3 -m pytest`. Platform verification requires real target machines.
