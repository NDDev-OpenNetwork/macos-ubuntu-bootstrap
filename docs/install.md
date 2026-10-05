# Installation guide

Run `scripts/bootstrap.sh`; platform installers are internal composition layers.
Plan mode is the default and Ubuntu always requires an explicit profile.

```bash
bash scripts/bootstrap.sh --platform macos [--no-gui] [--apply]
bash scripts/bootstrap.sh --platform ubuntu --profile desktop [--no-gui] [--apply]
bash scripts/bootstrap.sh --platform ubuntu --profile desktop-builds [--no-gui] [--apply]
bash scripts/bootstrap.sh --platform ubuntu --profile desktop-server [--docker-mode none|rootful|rootless] [--apply]
bash scripts/bootstrap.sh --platform ubuntu --profile server [--apply]
```

`desktop` provisions editing, LSPs, scanners, formatters, terminal tooling, and
local static checks without Docker. `desktop-builds` adds rootful Docker for
local builds/tests. `server` configures a headless Docker server and keeps risky
network hardening behind explicit flags.

The source-analysis baseline covers the estate's active Python, JavaScript and
TypeScript, Svelte, SQL, Go, Rust, Dart, Kotlin, C/C++, shell, YAML, JSON,
HTML/CSS, TOML, Markdown, Terraform, CMake, Dockerfile, GitHub Actions, and
Ansible sources. Ubuntu receives JetBrains' official standalone Kotlin LSP;
Swift and SwiftUI remain a macOS responsibility because useful SourceKit
analysis depends on Apple's SDK toolchain.

`desktop-server` targets Ubuntu 24.04 amd64 and combines the complete GUI and
server baselines. It defaults to no Docker; pass `--docker-mode rootful` (or
`rootless`) when the host also builds, deploys and tests locally. XRDP stays
exclusively on `127.0.0.1:3389`; do not add a public firewall rule for that
port. Generate
client files only after deployment, when the public host name, SSH account and
server Ed25519 public host key are known. The complete workflow is in the
[desktop-server reference](reference/desktop-server.md).

Every profile installs all seven official vendor CLIs: Antigravity (`agy`),
Claude Code (`claude`), Codex (`codex`), Cursor (`cursor-agent`), Grok Build
(`grok`), OpenCode (`opencode`), and Pi (`pi`). Program versions and full
platform-artifact digests are imported from the published 0.0.88 setup-system
baselines. These are the vendor programs, not configuration mutations: setup
profiles, authentication and running agent sessions remain untouched.

`scripts/managed_cli.py` downloads exact artifacts, verifies byte length and
SHA-256 before extraction or execution, and writes a receipt covering the whole
payload, including bundled runtimes and auxiliary files. A repeat apply checks
that receipt and performs no download. Existing owner-held PATH launchers are
moved to private backups before replacement; divergent managed payloads are
refused and preserved. No network response is executed as a shell script.
The `cx`, `cl` and `gk` convenience launchers retain their previous behavior.
Linux Cursor uses the already-required, verified bootstrap Node 24 runtime; its
launcher and receipt bind that dependency without changing the vendor archive.
A missing, modified or incompatible-major Node is refused, never replaced by an
ambient PATH command. macOS keeps the bundled Cursor runtime.

Herdr is a required terminal tool on macOS and every Ubuntu profile. Both
platforms install the pinned architecture-specific binary from the official
`herdrdev/herdr` GitHub release and verify its checksum, managed launcher,
runtime receipt, and exact version. Ubuntu also installs a user-systemd oom
guard that moves MCP and language-server processes into a killable cgroup so
systemd-oomd cannot take the multiplexer down with them. Bootstrap does not depend on a lagging
or subsequently updated Homebrew formula for the managed macOS runtime. The pinned upstream identity,
independently verified asset hashes, and update policy are recorded in the
[dependency source register](reference/source-register.md).

Ubuntu also pins the operator CLIs already used on the estate hosts: `doctl`,
`stripe`, and the Google Cloud SDK (`gcloud`/`gsutil`/`bq`) as hashed release
archives, plus `resend` and `wrangler` as exact npm versions installed through
Bun. Unmanaged copies already on `~/.local/bin` are adopted aside and replaced
with the managed launcher. `gh` remains an apt package. GoDaddy CLI (`gddy`) is installed from the official `godaddy/cli` release,
with exact per-platform digest and payload receipts. Operator-authored
wrappers (`cf`, `cfapi`) remain outside this contract.

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

Validate changes with `bash scripts/ci/setup-test-env.sh` once, then
`bash scripts/ci/lint.sh`, `bash scripts/ci/validate.sh` and
`.venv/bin/python -m pytest`. The setup script is idempotent and establishes
the real zsh and hash-locked Python 3.14 environment the suite asserts
against. Platform verification requires real target machines.
