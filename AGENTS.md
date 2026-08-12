# rldyour macOS or Ubuntu Bootstrap

## Purpose

This repository owns plan-first bootstrap and verification for the rldyour AI
CLI environment on Apple Silicon macOS desktops, Ubuntu 24.04/26.04 desktops,
and headless Ubuntu 24.04/26.04 servers.

It is an adapter, not an upstream AI runtime. Keep installation logic,
verification, contract metadata, tests, and documentation synchronized.

## Sources Of Truth

- Public compositor: `scripts/bootstrap.sh`
- Shared helpers and managed browser layer: `scripts/lib/common.sh`
- macOS installer/verifier: `scripts/macos/install.sh`, `scripts/macos/verify.sh`
- Ubuntu installer/verifier: `scripts/ubuntu/install.sh`, `scripts/ubuntu/verify.sh`
- Ubuntu server module/verifier: `scripts/ubuntu/server.sh`, `scripts/ubuntu/verify-server.sh`
- Authentication handoff: `scripts/auth-handoff.sh`
- Machine-readable contract: `config/rldyour-contract.json`
- Profile/browser decision: `docs/adr/0004-profile-composition-and-cloakbrowser-boundary.md`
- Language-server host decision: `docs/adr/0005-go-and-rust-language-server-hosts.md`
- Operator guide: `README.md`, `docs/install.md`, `SECURITY.md`
- Product version: `VERSION`, `CHANGELOG.md`

When prose and implementation disagree, verify the scripts and contract, then
update the affected documentation in the same change. Do not invent a second
policy source.

This file is the only guide. `.claude/CLAUDE.md` imports it and carries a short
delta; `.serena/memories/` holds one pointer and no policy. That shape is held
by `tests/test_agent_context.py`, which fails if the Claude file grows back into
a specification, if either surface copies a pin the contract owns, or if the
memory corpus regrows. Prefer making a rule checkable over writing it down
twice: a rule that can be tested belongs in a test, a decision belongs in an
ADR, a version belongs in the contract.

## Contract `2.6.1`

Ubuntu profile selection is always explicit. Never infer server/rootful Docker
from `uname=Linux`; require `--profile desktop|desktop-builds|server`.

Supported compositions:

- Apple Silicon macOS: `desktop`, GUI enabled or disabled, Docker `none`,
  `source-lsp-only`.
- Ubuntu 24.04/26.04 `amd64` or `arm64` desktop: GUI enabled or disabled,
  Docker `none`, `source-lsp-only`.
- Ubuntu 24.04/26.04 `amd64` or `arm64` desktop-builds: GUI enabled or disabled,
  Docker `rootful`, `local-dev-with-builds` (everything desktop has PLUS Docker
  for local builds/tests, without the server baseline).
- Ubuntu 24.04/26.04 `amd64` or `arm64` server: headless, Docker
  `none|rootful|rootless`, default `rootful`, `container-execution-only` (project
  builds/tests run inside Docker; the host installs no build toolchain or SDKs).

macOS never accepts the server or desktop-builds profile. The plain desktop
profile never installs Docker or configures local project build/runtime
execution; desktop-builds is the explicit exception (ADR 0008). `--no-gui`
removes only the GUI overlay; it does not change the execution policy. Server is
Ubuntu-only and always headless.

Desktop and desktop-builds profiles additionally install Go, Rust, and the Dart SDK as
language-server hosts for `gopls`, `rust-analyzer`, and the Dart analysis server,
on the same footing as Node, Python, and LLVM — present to resolve source, not to
authorize project builds (ADR 0005, ADR 0006). Dart also provides
`dart mcp-server`, the transport the `dart-flutter` MCP server in `rldyour-mcps`
executes; the Flutter SDK is not installed because its `bin/cache` self-populates
and would mutate a receipt-verified tree. The server profile receives no host
toolchain: `install_compiled_language_hosts` returns early there.

## Managed Versions

**Every exact version and digest lives in `config/rldyour-contract.json`.** It
is the only place they are correct, parity with the installers is enforced by
`tests/test_contract_parity.py`, and a copy in prose is a copy that goes stale.
Read the contract; do not read a version here.

What the contract cannot express is the reasoning, so only that is recorded:

- **One owner per harness (RVR-P1-004).** The active set is `codex`, installed
  by its authoritative NDDev module, never inline and never through a bun/npm
  global. This is now checkable rather than asserted: `harnesses.detection`
  makes `device_integrity` report a `codex` resolving outside its module's
  target as drift. `zcode` is catalogued but **on-pause** — bootstrap never
  installs, starts, verifies, removes or adopts it, and an installed copy is
  recorded as evidence only.
- **The codex module is applied with its unrestricted `full-auto` setup.** This
  is an owner-controlled workstation and the profile is chosen deliberately.
  Anyone hardening a device that is not owner-controlled must revisit it first
  (`SECURITY.md`).
- **CloakBrowser passes `--no-sandbox` on Linux only.** Ubuntu 23.10+ restrict
  unprivileged user namespaces through AppArmor, so without it the zygote aborts
  and the mandatory browser layer cannot start at all. macOS keeps its sandbox
  and the flag must never appear there. Do not relax
  `kernel.apparmor_restrict_unprivileged_userns` instead: that re-enables
  unprivileged user namespaces for every process on the host to fix one browser.
- **Go, Rust and Dart are language-server hosts, not build authorization**
  (ADR 0005, ADR 0006). Desktop and desktop-builds only;
  `install_compiled_language_hosts` returns early on the server profile, which
  stays `container-execution-only`. The Flutter SDK is deliberately absent: its
  `bin/cache` self-populates and would mutate a receipt-verified tree.
- **Google Chrome is pinned by signing key, not by version.** Pinning a browser
  to an old build is a security liability, and the pin would be fiction anyway
  because the vendor's repository moves the package underneath it. The key
  fingerprint is verified before the repository is trusted.
- **An architecture upstream does not publish is declared absent, never faked.**
  Telegram ships x86_64 only; its arm64 fields are empty and the row is skipped
  there. Filling them with the x86_64 values made an arm64 device verify the
  digest of a binary it cannot execute.
- **Adding a pinned tool means adding a row.** `PINNED_SOURCE_TOOLS`,
  `USER_TOOLS` and `DESKTOP_DEBS` each have exactly one installer. A second
  install path is how one entry quietly stops being verified.

Use current, source-backed facts before changing a dependency, and confirm a
digest by downloading the artifact rather than copying a release note. Never
reintroduce mutable, unauthenticated installer execution or unfrozen dependency
resolution.

## Non-Negotiable Browser Boundary

CloakBrowser is mandatory on every profile. A managed launchd or systemd user
service owns `http://127.0.0.1:9222`. Chrome DevTools MCP, Playwright CLI, and
the exact disabled Webwright tombstone are repository-managed. Only Chrome
DevTools MCP and Playwright CLI are active and may use the fixed endpoint;
Webwright must exit `78` without starting Python or a browser.

There is no supported `--skip-browser`, `RLDYOUR_SKIP_CLOAKBROWSER`, alternate
browser executable, alternate endpoint, auto-started stock browser, or stock
Chromium fallback. Playwright `run-code` and `--filename` are also forbidden.
Missing, unhealthy, or receipt-divergent browser state must fail closed. Never
bind the CDP listener beyond loopback. Use `scripts/verify-browser-runtime.sh`
as the exact installed-runtime authority.

Preserve unmanaged browser files and fail instead of adopting or replacing
them. The only adoption exception is the complete byte/shape-verified legacy
rldyour CloakBrowser home, launcher pair, and service template. Its migration
must snapshot the home, all six browser wrappers, and active service state;
failed handoff must restore them transactionally. Browser Node staging must
remove group/world-write bits before publication and rebuild an already unsafe
managed runtime from the frozen lock while preserving the rejected tree.
Runtime browser profiles, traces, caches, tokens, and service state must never
be committed.

## GUI And Integrity Boundaries

- macOS GUI: Ghostty, cmux, ChatGPT, and the separate Codex app.
- Ubuntu GUI: no bootstrap-installed harness apps; the ZCode desktop app is
  installed by the `nddev-harnesses` repository. Desktop customization
  (GNOME dock, Russian layout, Google Chrome install, optional RustDesk,
  Firefox removal) is owned by `scripts/ubuntu/desktop.sh`. Google Chrome is the
  standard browser and is pinned by signing-key fingerprint rather than by
  version; BrowserOS was removed from the standard set by owner decision and an
  already-installed copy is left alone.
- Ubuntu server: no GUI applications.

macOS GUI apply configures cmux non-interactively only for Codex. Do not replace
that targeted `--yes` install with broad interactive `cmux hooks setup`, which
can create unrelated agent configs.

ZCode is owned by the `nddev-harnesses` repository and installed through its own
lifecycle. Bootstrap never installs ZCode via an apt `.deb` or a
`RLDYOUR_ZCODE_SHA256` gate; both were removed in contract `2.0.0`, and the
remaining module delegation was removed in `2.6.0`. Do not reintroduce a silent
download, fallback checksum, or integrity bypass.

Authentication is a post-install owner handoff. `scripts/auth-handoff.sh` may
show instructions and perform non-secret status probes, but bootstrap code must
not read, print, store, upload, or synthesize credentials.

## Ubuntu Server Safety

Plan mode is the default. Rootful Docker is the composed server default, but
the installer never grants Docker group membership. Rootless and `none` remain
explicit alternatives.

The full Ubuntu compositor runs as the non-root sudo-capable developer account
that owns its home and systemd-user browser service. Root-only automation may
use the sourceable server layer, not install AI state under `/root`.

UFW, key-only SSH, and Fail2ban are independent explicit opt-ins. Never infer
them from the server profile. Preserve these safeguards:

- require a non-root account with a readable supported public key before
  disabling password authentication;
- require `ssh-keygen` parsing and StrictModes-safe key path metadata;
- validate OpenSSH syntax and full `sshd -T -C` user/client/local connection
  contexts before reload, including a separate root context;
- preserve the active/enabled `ssh.service` versus `ssh.socket` provider and
  never restart a socket for authentication-only changes;
- restore the previous managed SSH drop-in after validation or reload failure;
- add the SSH allow rule before enabling UFW;
- validate the Fail2ban jail before restart;
- restore prior Fail2ban file/service state after activation failure;
- preserve existing synchronized NTP/PTP providers;
- warn operators to keep the current SSH session open until a second connection
  succeeds;
- do not pretend UFW alone contains Docker-published ports;
- do not add generic sysctl or resource-limit tuning without a separate,
  host-specific decision.
- never upgrade apt packages or an existing healthy Docker runtime implicitly;
  fail on partial/custom Docker state.

Full server validation requires a real supported Ubuntu VM with systemd.

## Implementation Rules

- Keep shell entry points strict, idempotent, plan-aware, and non-interactive
  unless an explicit owner handoff is the purpose.
- Never pipe a remote network stream directly into a shell. Download to a
  temporary file, verify available integrity metadata, then execute.
- Update managed files atomically. Preserve unmanaged or user-modified files
  and fail with a clear explanation.
- Keep shell policy in owned `~/.config/rldyour/` drop-ins. Modify owner shell
  files only through the delimited, backed-up source blocks and verify a fresh
  login shell after apply.
- Ubuntu Node.js, uv, Bun, Go, and Rust must retain verified runtime receipts
  and exact managed links; an external same-version PATH binary is not
  provenance.
- APT key validation must reject bundles with more than one primary key.
- Keep desktop source/LSP manifests free of Docker and general project runtime
  dependencies.
- Keep server build/runtime and hardening behavior in the Ubuntu server layer.
- Prefer existing shared helpers and namespaced server functions over duplicate
  shell logic.
- Do not swallow errors, fake successful checks, or downgrade mandatory checks
  to best-effort behavior.
- Do not commit credentials, `.env` files, local browser state, caches, traces,
  diagnostics output, or runtime markers.

## Common Commands

Plan:

```bash
bash scripts/bootstrap.sh --platform macos
bash scripts/bootstrap.sh --platform macos --no-gui
bash scripts/bootstrap.sh --platform ubuntu --profile desktop
bash scripts/bootstrap.sh --platform ubuntu --profile server
```

Apply:

```bash
bash scripts/bootstrap.sh --platform macos --apply
bash scripts/bootstrap.sh --platform ubuntu --profile desktop --apply
bash scripts/bootstrap.sh --platform ubuntu --profile server --apply
```

Supported skip flags are `--skip-system`, `--skip-ai`, `--skip-lsps`, and
`--skip-checks`. Do not document a browser skip.

Authentication handoff:

```bash
bash scripts/auth-handoff.sh show
bash scripts/auth-handoff.sh check
```

## Verification Gates

Run checks matching the touched scope and report exact commands:

```bash
bash scripts/ci/lint.sh
bash scripts/ci/validate.sh
python3 -m pytest
```

**macOS verification is on-pause.** The estate has no Apple Silicon target
available, so no macOS claim in this repository is currently backed by a run.
The platform is still supported and its code is still maintained — two defects
were fixed there on 2026-08-12 — but those fixes are argued from shell semantics
and covered by static tests, not proven. Treat any macOS statement as unverified
until a target exists, and never present a plan-mode run or a static test as
runtime evidence for it. The hosted CI lane stays: plan mode and shellcheck on
`macos-latest` are the only macOS signal there is, and they are cheap.

Use platform verification on real targets when platform behavior changes:

```bash
bash scripts/macos/verify.sh --strict
bash scripts/ubuntu/verify.sh --strict
bash scripts/ubuntu/verify-server.sh --docker-mode rootful
```

A real-target lane exercises the Ubuntu apply branches a stub cannot reach —
fresh Chrome install, key refusal, pinned `.deb` install, digest refusal —
against a disposable Ubuntu 26.04 container. It is opt-in because each case
pulls packages:

```bash
RLDYOUR_CONTAINER_TESTS=1 python3 -m pytest tests/test_container_apply.py
```

It does not replace the deterministic suites, and it is not a VM: systemd, a
GNOME session and macOS remain out of reach and are named rather than skipped
quietly.

For documentation-only changes, at minimum run `git diff --check` and targeted
stale-fact scans. Do not claim macOS, Ubuntu GUI, SSH, firewall, systemd, or
Docker runtime evidence that was not actually produced.

## Git And Delivery

- Preserve unrelated user changes in a dirty worktree.
- Use atomic Conventional Commits when commits are requested.
- Keep implementation, tests/validators, docs/policy, and generated metadata
  independently reviewable when practical.
- Do not force-push `main` or rewrite pushed history without explicit approval.
- Releases support numeric tag pushes and a numeric `workflow_dispatch` input.
  Manual dispatch must use the exact `origin/main` commit, require its green
  `bootstrap-gate`, and verify an already existing exact non-rewritten tag.
  Root automation is the sole tag creator; the pinned reusable workflow owns
  immutable release publication.
- Move any superproject gitlink only after this repository's changes are pushed
  and verified.
- **CodeQL mode is `default`, and `.github/workflows/codeql.yml` is inert.**
  Code scanning runs through CodeQL default setup (configured 2026-07-31 for
  `actions` and `python`); the tracked advanced-setup workflow is
  `disabled_manually` at the platform and last ran 2026-07-03, failing. The file
  is kept for a possible switch back, but do not read its presence as evidence
  that it runs — check `GET /repos/{owner}/{repo}/actions/workflows`. Exactly
  one mode is intended at a time: re-enabling the workflow means disabling
  default setup first, because configuration attachment is atomic and forcing
  default setup onto a repository with an active advanced setup fails the whole
  attachment.
- This repository is public, so `pull_request` executes untrusted fork code.
  Every job runs on a GitHub-hosted runner, whether it is selected by a
  reusable caller's `runner` input or by the job's own `runs-on` — matrix
  values included. `tests/test_agent_context.py` rejects any value outside the
  hosted set on either path.

  The rule is the estate runner platform's own, not this repository's
  invention. `modules/github-actions` builds disposable one-job Incus/KVM
  workers, and its `docs/threat-model.md` lists as a non-negotiable control:
  **no public/fork code on a trusted runner group**. Its cache plane says the
  same from the other side — public and fork jobs get no cache credential and
  are "retained on GitHub-hosted capacity" (`docs/cache-plane.md`, ADR 0020).
  A public repository routing a job onto that fleet would violate the platform's
  contract, not merely this file's preference.

  Check the *value*, never just the key, and use an allowlist of hosted labels
  rather than a denylist of fleet ones. The fleet publishes scale-set classes
  `nddev-linux-fast`, `nddev-linux-standard`, `nddev-linux-integration` and
  `nddev-linux-release`; the former `amsterdam` label is retired. Two reasons
  the allowlist is the only gate that holds: the set changes — that list is
  current as of 2026-08-12 and a denylist would silently go stale — and a job
  requesting a label no runner advertises does not fail, it queues
  indefinitely. A wrong value here is a hang, not a red check.

  Verified 2026-08-12 against `ci-workflows`: of 54 workflow files, 44 declare a
  `runner` default and every one is hosted, both at the pinned commit and on
  `main`. Nothing defaults to self-hosted today, so the explicit value is
  defence against a future change — and it stays, because the default belongs to
  the pinned commit and Dependabot bumps that pin weekly with no diff here.
  Two callers expose no `runner` input; their exemption is written next to the
  call and the test pins the list so a bump has to re-justify it.
