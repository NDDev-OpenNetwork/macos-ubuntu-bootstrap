# Changelog

All notable changes are documented here. The project follows Semantic
Versioning; the contract version in `config/rldyour-contract.json` moves with it.

## [Unreleased]

## [0.2.6] - 2026-09-15

- Pin osv-scanner to 2.6.0 after independently hashing the linux amd64 and
  arm64 GitHub release binaries against `osv-scanner_SHA256SUMS`.
- Pin JetBrains kotlin-lsp to 263.4702.0 from `download-cdn.jetbrains.com`,
  verifying both architecture tarballs against the published `.sha256` files.

## [0.2.5] - 2026-09-15

- Name `desktop-server` in the `--profile` error and document
  `--docker-mode rootful|rootless` for a host that builds locally. Installer
  behaviour was already that in 0.2.4; the comment lagged.
- Pin reusable workflows to current module mains.

## [0.2.4] - 2026-09-15

- Hash root-owned 0600 privilege records through `root_exec` when the applying
  user cannot read them. An interrupted contract upgrade that already published
  a different adapter JSON is asided and replaced; helper and policy still
  never replace.

## [0.2.3] - 2026-09-15

- Ubuntu privilege can take a new contract JSON when helper and policy already
  match this source: aside the prior contract and records, then publish. A
  partial transaction that is not that completed-bundle case still fail-closes.
- Apply still runs strict verify before writing a device receipt, but does not
  compare a prior receipt to the state this apply is about to record. Standalone
  `verify.sh --strict` still does.

## [0.2.2] - 2026-09-14

- Keep Ubuntu `--plan` from calling `bun pm bin -g` or `bun pm ls -g` when
  describing npm `user_tools`. Those probes create `~/.bun/install/global`
  before they can answer, so a plan wrote into the home it only describes.
  Hosted unit tests missed it because they do not have `bun` on PATH.

## [0.2.1] - 2026-09-14

- Republish the 0.2.0 contract: tag `0.2.0` landed on the merge commit, which
  GitHub does not attach to a pull request, so release evidence lookup refused
  publication. This tag is the PR-head commit after merge.
- Resolve bun's actual global bin (`bun pm bin -g`, including
  `~/.cache/.bun/bin`) when installing `resend` and `wrangler`, instead of
  assuming `~/.bun/bin`. Hosted native evidence used the cache prefix.

## [0.2.0] - 2026-09-14

- Add Ubuntu's distribution-owned PyYAML binding to the baseline so estate
  diagnostics and plan-state readers work with system Python on a clean host.
- Register already-installed operator CLIs (`doctl`, `stripe`, `gcloud`,
  `resend`, `wrangler`) as contract `user_tools` so device receipts name them.
- Record `require_extra_approval_for_unattributed_changes: false` on the `main`
  ruleset so Cursor co-authors do not trip GitHub's extra-approval gate.
- Add the Ubuntu 24.04 amd64 `desktop-server` profile: the GUI workstation and
  server baseline, with Docker disabled by default and XRDP restricted to
  `127.0.0.1:3389` behind an owner-managed OpenSSH tunnel.
- Add a credential-free deployment-time client renderer for macOS and Windows.
  Generated clients pin the Ed25519 SSH host key, fail over between ports 22
  and 443, verify local tunnel readiness, and include normal and constrained
  network RDP profiles.
- Preserve the proven Amsterdam XRDP 0.10 installation while fresh hosts use
  the signed Ubuntu package candidate without implicitly upgrading an existing
  healthy package. Record clean apply, repeat, reboot and cross-platform client
  proof as explicit real-host evidence still required.
- Refresh Homebrew.pkg to 7.0.1 and lazygit to 0.65.1 with reviewed upstream
  artifacts and per-architecture hashes.
- Refresh Bun to 1.4.2, Go to 1.27.1, Rust to 1.98.1, and Dart to 3.13.3 after
  independently verifying every supported architecture against official
  checksums. Add pinned Svelte and SQL language servers on both desktops and
  JetBrains' official standalone Kotlin LSP on Ubuntu.
- Consume Go through its immutable official toolchain module on
  `proxy.golang.org`, retaining per-architecture artifact hashes while avoiding
  the `dl.google.com` binary endpoint that is unavailable on some server
  networks.
- Migrate Ubuntu's exact vendor-generated Chrome Deb822 source into a root-only
  recovery backup before publishing the managed source, eliminating duplicate
  repository identities without accepting edited or redirected files.
- Extend the device-integrity receipt schema and policy resolver to record and
  verify the `desktop-server` profile.

## [0.1.3] - 2026-09-13

- Keep the Herdr multiplexer alive when systemd-oomd sheds a cgroup. Ptyxis
  launches Herdr inside one transient scope, so oomd killing that leaf takes
  every agent, MCP server and language server with it. Install a sibling
  `herdr-reclaim.service`, move MCP and LSP processes into it, and mark the
  Herdr unit `ManagedOOMPreference=omit`; shed at 25% pressure so pressure
  falls before oomd picks an unrelated leaf.

- Make ordinary merge CI advisory while preserving structural branch protections
  and independent release evidence gates; accept an explicit empty required-check
  policy without accepting malformed live observations.
- Consume verified current reusable-workflow commits and declare the numeric
  release tag style used by this module.

- Publish unsuccessful completed self-workflow attempts as unassigned,
  repository-local CI evidence; preserve actual conclusions and exact attempts.
- Register unreleased workflow dependencies by exact commit identity without
  claiming a stable release; reject mismatched development metadata.
- Refresh the Grok installer integrity pin after reviewing the current official
  script. Preserve checksum-before-execution and vendor-owned CLI boundaries;
  document review scope and the distinction from native installation evidence.

- Corrected the support-evidence description from thirteen to twenty-six
  hosted artifacts, separated accepted Ubuntu 26.04 server/reboot/SSH/UFW and
  Docker evidence from the remaining real-host gaps, added native Ubuntu 24.04
  and 26.04 ARM64 rootless Docker evidence, added native Ubuntu 26.04
  amd64/arm64 no-GUI evidence, and made every
  machine-readable gap name its exact remaining proof.
- Refreshed verified official-source pins for Codex, Homebrew.pkg, Herdr,
  Telegram, OSV Scanner, yq and ast-grep; recorded explicit evidence holds for
  Bun, Go, Rust and Dart transitions that still lack complete platform hashes.

## [0.1.2] - 2026-08-25

### Fixed

- Refreshed the Anthropic-hosted Claude Code installer digest after two
  independent official-source downloads produced identical new bytes.
- Replaced twelve untagged reusable-workflow pins falsely labeled `0.13.3`
  with the signed public `0.1.3` release commit, and added an offline registry
  validator that rejects mismatched SHA/version comments and undeclared pins.

## [0.1.1] - 2026-08-16

First release of `macos-ubuntu-bootstrap` as an open-source adapter under
`NDDev-OpenNetwork`. The version line starts here, and the device contract
starts with it: a contract version is consumed by devices, so carrying forward a
number whose releases this repository cannot produce would make every device
state comparison reference something unresolvable.

### Added

- **Four device classes**: macOS desktop, Ubuntu desktop, Ubuntu desktop-builds
  and Ubuntu server, each with plan, apply and verify, and clean-device evidence.
- **A privileged descendant supervisor** for the Ubuntu path, proven in
  containers against all five failure modes it exists for: a descendant that
  traps and ignores TERM, a process in a different session, the helper running as
  PID 1, an exited-but-unreaped child, and a background job in another process
  group. Every one of those was invisible to `shellcheck` and `bash -n`.
- **A twenty-one lane platform-evidence matrix** on real hosted macOS and Ubuntu
  runners, so apply and verify behaviour is observed rather than asserted.
- **A ruleset mirror bound to the live branch.** `check_required_contexts.py`
  compares `.github/rulesets/branch-main.json` against the rules API on every
  pull request, so the mirror cannot claim a protection the branch does not have.
- **Digest-pinned tool provisioning**: language toolchains, agent harnesses and
  browser components install from vendor artifacts verified by checksum, with no
  mutable `@latest` and no stream-to-shell in any executable path.

### Notes

The harness model is `policy: vendor-official`. Codex, Claude Code and
grok-build install from digest-pinned vendor artifacts; there is no selected
harness module commit, and nothing here tracks the harnesses' own release
lifecycles.
