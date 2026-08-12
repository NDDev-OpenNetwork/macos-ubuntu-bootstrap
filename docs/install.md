# Installation And Target Matrix

This guide describes adapter contract `2.6.1`. All paths are relative to the
root of an existing checkout of this repository at a verified commit; acquiring
that checkout is the caller's step (see the GDS clean-device runbook, step 0).
Use `scripts/bootstrap.sh` as the
public entry point so platform, profile, GUI, Docker, browser, safety, and
verification settings are composed consistently.

## Supported Targets

- **macOS Apple Silicon:** `desktop`; GUI enabled by default or disabled with
  `--no-gui`; Docker `none`; policy `source-lsp-only`.
- **Ubuntu 24.04/26.04 desktop (`amd64`/`arm64`):** GUI enabled by default or
  disabled with `--no-gui`; Docker `none`; policy `source-lsp-only`.
- **Ubuntu 24.04/26.04 desktop-builds (`amd64`/`arm64`):** GUI enabled by
  default or disabled with `--no-gui`; Docker `rootful`; policy
  `local-dev-with-builds`. Everything desktop has, plus Docker Engine for local
  builds/tests — without the server baseline (no openssh-server,
  unattended-upgrades, or chrony). See ADR 0008.
- **Ubuntu 24.04/26.04 server (`amd64`/`arm64`):** headless; Docker `none`,
  `rootful`, or `rootless`; default `rootful`; policy `container-execution-only`
  (project builds/tests run inside Docker; no host build toolchain is installed).

macOS supports only the desktop profile. Ubuntu requires an explicit
`--profile desktop|desktop-builds|server`; the bootstrap never infers a runtime
or Docker role from Linux alone. Desktop, desktop-builds, and server are roles;
`--no-gui` removes only the GUI overlay and does not change the execution policy.

To pair a source/LSP-only desktop with a build server, provision both profiles
independently and put the same reviewed commit in both checkouts:

```bash
bash scripts/remote-exec.sh --host developer@build-host \
  --remote-repo /srv/work/project -- just check
```

Both worktrees must be clean and their exact HEAD must match. The adapter never
copies source or credentials and never repairs a remote checkout implicitly.

Apply mode validates the real target. Ubuntu apply is supported only on exact
Ubuntu releases `24.04` and `26.04`.

## Plan First

Every invocation defaults to a read-only plan. Review that output before adding
`--apply`.

```bash
# Apple Silicon macOS desktop
bash scripts/bootstrap.sh --platform macos
bash scripts/bootstrap.sh --platform macos --no-gui

# Ubuntu desktop
bash scripts/bootstrap.sh --platform ubuntu --profile desktop
bash scripts/bootstrap.sh --platform ubuntu --profile desktop --no-gui

# Ubuntu desktop-builds (desktop + Docker for local builds/tests)
bash scripts/bootstrap.sh --platform ubuntu --profile desktop-builds
bash scripts/bootstrap.sh --platform ubuntu --profile desktop-builds --no-gui

# Ubuntu server; rootful Docker is the bootstrap default
bash scripts/bootstrap.sh --platform ubuntu --profile server
```

Apply examples:

```bash
bash scripts/bootstrap.sh --platform macos --apply
bash scripts/bootstrap.sh --platform ubuntu --profile desktop --apply
bash scripts/bootstrap.sh --platform ubuntu --profile desktop-builds --apply
bash scripts/bootstrap.sh --platform ubuntu --profile server --apply
```

The platform can be auto-detected, but explicit `--platform` is preferable in
automation and reviewable runbooks.

The full Ubuntu composition must run from the non-root developer account that
will own the managed home and CloakBrowser systemd-user service; that account
needs sudo. Root/cloud-init automation may invoke `scripts/ubuntu/server.sh`
for the root-owned baseline only. This separation avoids silently building the
AI environment under `/root` without a usable user manager.

## Public Options

```text
--platform macos|ubuntu
--profile desktop|desktop-builds|server
--gui | --no-gui
--docker-mode none|rootful|rootless
--plan | --apply
--skip-system
--skip-ai
--skip-lsps
--skip-checks
--strict
--harden-ssh
--enable-ufw
--with-fail2ban
```

The three hardening flags are Ubuntu-server-only. Desktop profiles reject
Docker modes other than `none` and reject server hardening flags.

There is no compliant browser skip. `--skip-browser` and
`RLDYOUR_SKIP_CLOAKBROWSER=1` fail because every supported composition requires
the managed CloakBrowser boundary.

## Profile Composition

### Desktop: Source/LSP Only

Both desktop platforms receive:

- terminal and source-management utilities;
- Node/Python tool hosts required by managed CLIs and language tooling (Ubuntu
  pins the official Node.js `24.18.0` LTS tarball and both architecture hashes);
- the compiled-language and SDK hosts that back their language servers: Go
  `1.26.5` (gopls `v0.23.0`), Rust `1.97.1` (rust-analyzer), and the Dart SDK
  `3.12.2` (`dart language-server`). These are desktop-only — the server profile
  is `container-execution-only` and `install_compiled_language_hosts` returns
  early there. The Dart SDK also provides `dart mcp-server`, the transport the
  `dart-flutter` MCP server declared by `rldyour-mcps` executes, which is why both
  verifiers prove the subcommand responds instead of only checking that `dart`
  resolves (ADR 0005, ADR 0006). The Flutter SDK is deliberately not installed:
  its `bin/cache` self-populates at runtime and would mutate a hash-verified
  runtime tree;
- source-analysis, LSP, formatter, linter, quality, and security tools;
- managed AI CLIs;
- the mandatory fail-closed browser layer;
- an optional platform-specific GUI overlay;
- on Ubuntu desktop, user-selected tools (herdr `0.7.5` and Telegram Desktop
  `7.0.7`) installed as managed, SHA-256-verified binaries with `.desktop`
  launchers. Telegram's internal updater is disabled by a managed
  `externalupdater.d` policy so it cannot mutate the receipt-bound binary, and
  its Qt launcher uses XCB/XWayland on the estate's NVIDIA Wayland workstation.
  That policy also disables Telegram's built-in `InstallLauncher()`, so
  bootstrap publishes the upstream `org.telegram.desktop.desktop` identity and
  SHA-256-pinned application/symbolic tray icons from the matching source
  commit. It migrates an existing GNOME favorite before backing up and retiring
  recognized old launchers, then assigns both `tg://` and `tonsite://` to the
  canonical entry. User-owned divergent files are preserved and fail closed.
  These are declared in the contract under `user_tools` and `desktop_entries`.

Desktop manifests intentionally exclude Docker, project build orchestration,
language SDKs used as project runtimes, and local project test/runtime
provisioning. A tool-host runtime that supports an AI CLI or LSP does not change
that boundary. On macOS, clangd is delivered by Homebrew's LLVM distribution,
but the bootstrap never invokes its compiler/linker for a project. Build and
execute projects on an Ubuntu server profile or another explicit runtime host.

### Ubuntu Server: Build/Runtime

The Ubuntu server profile is headless and adds the server build baseline,
OpenSSH and update/time-service safeguards, server verification, and the
selected Docker mode. It also retains the terminal, LSP, AI CLI, quality, and
mandatory browser layers.

Docker choices:

- `rootful` - bootstrap default; installs Docker Engine and plugins but never
  adds a user to the root-equivalent `docker` group;
- `rootless` - explicit alternative for a non-root user after reviewing its
  networking, cgroup, storage, and privileged-port limitations;
- `none` - leaves Docker state unmanaged.

Examples:

```bash
bash scripts/bootstrap.sh --platform ubuntu --profile server --docker-mode rootful
bash scripts/bootstrap.sh --platform ubuntu --profile server --docker-mode rootless
bash scripts/bootstrap.sh --platform ubuntu --profile server --docker-mode none
```

## Managed Harnesses (one owner per harness)

The owner's active harness set is **codex** only. Bootstrap no
longer inline-installs any AI CLI and never installs a harness through a bun/npm
global path. Each harness is owned by its dedicated authoritative NDDev module.
GDS device bootstrap materializes each module checkout and passes its absolute
path in an environment variable. When a variable is unset, bootstrap does **not**
skip the harness: it self-materializes the owner module by cloning
`harnesses.<id>.module_repo` at the exact `harnesses.<id>.module_commit` from
`config/rldyour-contract.json` into
`~/.local/share/rldyour/harness-modules/<module>`, then runs that module's
install lifecycle. Setting the variable overrides this with an existing local
checkout, whose entrypoint is validated before use.

This means a clean OS -> bootstrap run installs codex with no manual steps and no
pre-provisioned checkouts.

| Harness | Owner module | Module path env (optional override) | Delegated install |
| --- | --- | --- | --- |
| Codex | `nddev-codex-app` | `RLDYOUR_CODEX_MODULE` | `install-cli`, `apply --setup safe`, then `install-builder` |

The codex module installs its CLI under its own target only and publishes no link
into the managed prefix, so `${RLDYOUR_CODEX_HOME:-$HOME/.codex}/bin` is part of
the managed PATH. Without it, `codex` could not be found and strict verification
could never pass.

### ZCode is delegated out of bootstrap

ZCode is **not** installed or delegated to from here (ADR 0006). The desktop app
creates and owns `~/.zcode` on first launch, and its installer correctly refuses
an unstamped target without an explicit `--adopt-unmanaged` — an adoption decision
that belongs to the operator, not to an unattended run. Because the harness step
ran before every other layer under `set -euo pipefail`, that refusal aborted the
whole apply and silently skipped the language servers, compiled hosts, pinned
scanners, and browser stack behind it. zcode is now declared
`harnesses.delegated` in the contract and installed by the **nddev-harnesses**
repository through its own lifecycle. Neither verifier requires `zcode`.

The codex setup uses the unrestricted `full-auto` profile on this
owner-controlled workstation. Re-running bootstrap reapplies the complete
profile, including both `config.toml` and `AGENTS.md`, so a stale safe instruction
file cannot contradict the runtime permissions. `RLDYOUR_DRY_RUN` is respected:
a codex dry run only logs the exact planned module commands.

The codex harness stays update-locked: both `DISABLE_AUTOUPDATER=1` and
`DISABLE_UPDATES=1` are exported by the managed shell drop-in so the module's
standalone binary cannot silently drift.

## Mandatory Browser Automation

Browser automation is a required platform layer, not an optional desktop app.

| Component | Pin | Contract |
| --- | --- | --- |
| CloakBrowser | `0.4.12` | only supported browser backend |
| Managed CDP service | `http://127.0.0.1:9222` | fixed loopback endpoint |
| Chrome DevTools MCP | `1.6.0` | wrapper supplies the fixed browser URL |
| Playwright CLI | `0.1.17` | wrapper supplies the managed CDP config |
| Webwright | retired fail-closed | exact disabled wrapper exits `78` |

CloakBrowser is installed in an isolated environment. launchd on macOS or a
systemd user service on Ubuntu owns the persistent headless process and its
managed profile. The Ubuntu service explicitly uses
`DBUS_SESSION_BUS_ADDRESS=disabled:` so a lingering user manager can start the
headless endpoint before login without activating GUI portal/keyring services
before GNOME exports its display environment. `cloakbrowser-cdp-health`
validates that isolation together with process ownership, command line,
loopback binding, discovery response, and WebSocket endpoint.

The only active providers are Chrome DevTools MCP and Playwright CLI. Their
wrappers run that health check before browser actions and reject:

- alternate CDP or WebSocket endpoints;
- alternate executables, channels, browser names, or configuration files;
- provider auto-start of stock Chrome or Chromium;
- Playwright arbitrary `run-code` or `--filename` execution;
- embedded or stock-browser fallback.

Every successful apply also publishes a canonical receipt that binds the exact
runtimes, provider binaries, wrappers, service definition, policy sources, and
live health proof. Verify the complete installed state with:

```bash
bash scripts/verify-browser-runtime.sh
```

A missing or unhealthy endpoint is a hard failure. Keep port `9222` bound to
`127.0.0.1`; exposing CDP remotely exposes browser pages, cookies, storage, and
JavaScript execution.

## GUI Overlay

### macOS

GUI mode installs the verified Homebrew casks for:

- Ghostty;
- cmux;
- ChatGPT;
- the separate [Codex desktop app](https://openai.com/index/introducing-the-codex-app/),
  installed through Homebrew's verified `codex-app` cask;
- Claude Desktop.

`--no-gui` skips these applications while preserving the desktop source/LSP,
AI CLI, terminal, and browser layers.

Existing casks are preserved without an implicit upgrade. Missing casks use
Homebrew's verified cask metadata; the repository does not pin mutable desktop
app versions.

### Ubuntu Desktop

GUI mode installs the desktop font support used by the terminal environment and
then runs `scripts/ubuntu/desktop.sh`, which owns desktop customization: the
GNOME dock moved to the bottom and centered, the Russian keyboard layout,
the Google Chrome install, the optional RustDesk install, and the complete removal of the stock snap and apt
Firefox. No harness desktop app is installed by bootstrap: the codex harness is
owned by its GDS module, and the ZCode desktop app is installed by
`nddev-harnesses`. ChatGPT, Codex, and cmux have no supported Linux desktop
build.

Ubuntu server never installs GUI applications.

### Harness ownership

The codex harness (CLI and setup) is installed and version-owned by its
authoritative NDDev module, not by this bootstrap. Bootstrap only delegates to
that module's own install lifecycle; it publishes no apt `.deb`, bun/npm global,
or frozen AI-CLI bundle for any harness. ZCode (CLI and desktop app) is owned
end-to-end by `nddev-harnesses` and is not delegated to from here at all.

## Explicit Ubuntu Server Hardening

No firewall, SSH authentication, Fail2ban, generic sysctl, resource-limit, or
Docker access change is inferred automatically. Plan mode remains the default.

The composed bootstrap exposes three independent opt-ins:

```bash
bash scripts/bootstrap.sh \
  --platform ubuntu \
  --profile server \
  --apply \
  --harden-ssh \
  --enable-ufw \
  --with-fail2ban
```

For an explicit SSH user, port, or UFW source CIDR, use the sourceable server
entry point after reviewing the composed bootstrap plan:

```bash
bash scripts/ubuntu/server.sh \
  --apply \
  --docker-mode rootful \
  --harden-ssh \
  --ssh-user deploy \
  --ssh-match-address 203.0.113.25 \
  --ssh-local-address 203.0.113.10 \
  --ssh-match-host admin.example.net \
  --ssh-port 22 \
  --enable-ufw \
  --ssh-allow-cidr 203.0.113.0/24 \
  --enable-fail2ban
```

Safety behavior:

- key-only SSH requires an existing non-root user and a readable supported
  public key in `authorized_keys`; `ssh-keygen` parsing plus StrictModes-safe
  owner/mode checks must pass;
- the managed OpenSSH drop-in is checked with `sshd -t` and effective settings
  are verified for the complete live connection tuple before reload;
- an SSH session supplies client/local addresses and local port automatically;
  console/cloud-init hardening must provide the explicit Match context shown
  above;
- a validation or reload failure restores the prior managed drop-in;
- an already active or enabled `ssh.service`/`ssh.socket` provider is preserved;
- authentication-only changes do not restart a socket-activated listener;
- UFW creates the SSH allow rule before enabling the firewall;
- Fail2ban validates the sshd jail before service restart;
- failed Fail2ban enable/restart/live-jail checks restore the prior file and
  service enable/active state;
- post-apply verification runs unless the low-level server module is explicitly
  invoked with `--skip-verify`.

An already synchronized clock or active NTP/PTP provider is preserved. The
bootstrap only installs Chrony when no provider is detected; verification still
requires the clock to reach a synchronized state.

Keep the current SSH session open until a second key-authenticated connection
works. Docker-published ports can bypass ordinary UFW input policy, so validate
exposure from outside the host and apply a host-specific network design.

## Authentication Handoff

Installation and authentication are intentionally separate. The repository
never manages credentials.

```bash
bash scripts/auth-handoff.sh show
bash scripts/auth-handoff.sh check
```

`show` documents owner-controlled sign-in for GitHub CLI, the Codex/OpenAI
harness, ZCode where `nddev-harnesses` installed it, supported desktop
applications, browser health, and cmux.
`check` performs only non-secret CLI status probes and reports `ok` or
`pending`; it does not print account secrets.

Headless Codex authentication uses `codex login --device-auth`. ZCode signs in
with Z.ai account OAuth on first launch.

## Ownership And Idempotency

Managed files are updated atomically and carry repository ownership markers.
Existing unmanaged files, symlinks, directories, or dirty managed-source
checkouts are preserved and cause a failure instead of being adopted or
overwritten. Existing global package installations outside the managed browser
prefix are not removed.

Shell integration uses owned `~/.config/rldyour/zshenv` and `zprofile` drop-ins
plus narrowly delimited source blocks in the owner's existing `~/.zshenv` and
`~/.zprofile`. Content outside those blocks is retained, the original file is
backed up before mutation, and a clean second apply makes no further backup or
change. Fresh-login verification proves managed PATH precedence, tool
resolution, CloakBrowser routing, trust-override removal, and updater policy.
Interactive modern-tool aliases and abbreviations are enabled only when their
target executable exists; Ubuntu's `batcat` and `fdfind` command names are
selected automatically.

Ubuntu Node.js, uv, and Bun use immutable versioned release assets plus tracked
per-architecture SHA-256 values. Each extracted Ubuntu runtime carries an owned
receipt binding the tracked archive digest to hashes of its managed
executables; strict verification also requires the owned `~/.local/bin` links.
External same-version PATH binaries are never accepted as provenance. Homebrew
uses a hash-verified, signed, and
notarized package. The codex harness is installed by its authoritative NDDev
module (`nddev-codex-app`), which owns its pinned standalone artifacts and
integrity checks; bootstrap only delegates to that module's install lifecycle and
never installs a harness through a bun/npm global path. Chrome DevTools MCP and Playwright
CLI install from a separate tracked `bun.lock` with `--frozen-lockfile`.
CloakBrowser dependencies come from a tracked universal lock and install with
`uv sync --frozen`. Webwright has no installed runtime or dependency tree.
Digest drift is a hard failure that requires a reviewed contract update.

APT uses `--no-upgrade` for already present baseline packages. Existing uv/Bun
source tools and a complete healthy Docker CE installation are preserved on
rerun; partial, unhealthy, custom, or unowned Docker state causes a fail-closed
handoff instead of an automatic install/upgrade over live workloads.
Existing Homebrew formulae and casks are also preserved: the macOS profile
installs missing entries but never runs an implicit `brew upgrade`.

Secrets belong in owner-controlled credential stores or local secret files,
never in tracked templates, logs, CI artifacts, or repository history.

## Verification

Repository checks:

```bash
bash scripts/ci/lint.sh
bash scripts/ci/validate.sh
```

Platform checks:

```bash
bash scripts/macos/verify.sh --strict
bash scripts/ubuntu/verify.sh --strict
```

Independent Ubuntu server checks:

```bash
bash scripts/ubuntu/verify-server.sh --docker-mode rootful
```

Browser runtime checks:

```bash
cloakbrowser-cdp-health
chrome-devtools-mcp --version
playwright-cli --version
```

Device integrity receipt — binds the device to the contract it was bootstrapped
against. Build snapshots the current device state (runtime hosts, pinned tools,
user tools, desktop entries, policy hashes) into a canonical-JSON receipt at
`~/.local/share/rldyour/device-receipt.json` (mode `0600`). Verify re-collects
state and compares structurally (detects binary changes, missing files) AND
compares every declared version against `rldyour-contract.json` (closes the gap
where `verify.sh` compares against hardcoded bash literals):

```bash
python3 scripts/device_integrity.py build
python3 scripts/device_integrity.py verify [--json]
python3 scripts/device_integrity.py metadata-only --receipt <path>
```

Full server evidence requires an Ubuntu 24.04/26.04 VM with systemd. A container
cannot prove SSH reachability, UFW behavior, time synchronization, Docker daemon
mode, or externally observable port exposure.

## Quick Reference

### Full device bootstrap (via GDS orchestrator)

```bash
cd ~/Developer/control-plane/github-device-sync

# Plan (read-only)
scripts/bootstrap-device.sh --device estate/devices/<device>.yaml --plan

# Apply (needs sudo for OS layer)
scripts/bootstrap-device.sh --device estate/devices/<device>.yaml \
  --apply --approval-ref approval:owner:<ref>

# Verify
python3 modules/macos-ubuntu-bootstrap/scripts/device_integrity.py verify
```

### OS installer directly

```bash
cd ~/Developer/control-plane/github-device-sync/modules/macos-ubuntu-bootstrap

bash scripts/bootstrap.sh --platform ubuntu --profile desktop-builds --gui --plan
bash scripts/bootstrap.sh --platform ubuntu --profile desktop-builds --gui --apply
bash scripts/ubuntu/verify.sh
```

### Profile → flags matrix

| What you want | Command flags |
|---|---|
| Local coding only (like macOS) | `--profile desktop` |
| Local coding + Docker builds | `--profile desktop-builds` |
| Headless server with Docker | `--profile server` |
| macOS desktop | `--platform macos` (auto-resolves to desktop) |
| Server with rootless Docker | `--profile server --docker-mode rootless` |
| Server without Docker | `--profile server --docker-mode none` |
| Desktop without GUI | `--profile desktop --no-gui` |

### CI validation (before push)

```bash
bash scripts/ci/validate.sh          # shellcheck + contract parity + plan matrix
uv venv .venv && uv pip install -r requirements-test.txt
.venv/bin/python -m pytest tests/ -q  # 176 tests
```

### Manual steps after bootstrap

```bash
sudo usermod -aG docker $USER         # docker group (desktop-builds/server)
# re-login for group to take effect

# SSH keys, Claude CLI, git identity — see "What is NOT installed" section
```
