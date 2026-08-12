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

GUI profiles install current Google Chrome stable. macOS also installs the
desktop applications listed in the contract. Ubuntu GUI installs RustDesk and
Telegram, configures GNOME, and removes Firefox. `--no-gui` retains command-line
tools, Herdr, language servers, and source checks.

Server hardening is explicit:

```bash
bash scripts/bootstrap.sh --platform ubuntu --profile server --apply \
  --harden-ssh --enable-ufw --with-fail2ban
```

Keep the current SSH session open until a second key-authenticated connection
succeeds. UFW alone does not contain Docker-published ports.

Validate changes with `bash scripts/ci/lint.sh`, `bash scripts/ci/validate.sh`,
and `python3 -m pytest`. Platform verification requires real target machines.
