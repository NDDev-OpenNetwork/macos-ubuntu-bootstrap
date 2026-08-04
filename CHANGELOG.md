# Changelog

All notable changes to this module will be documented in this file.

## [Unreleased]

## [2.5.0] - 2026-08-04

### Added

- **herdr** (terminal workspace manager for AI coding agents) is now installed
  on the Ubuntu desktop profile as a managed, SHA-256-verified binary with a
  `.desktop` launcher. Declared in the contract under `user_tools` with per-arch
  digests; installed via the same `ensure_pinned_source_tool` path as pinned
  source tools, with a runtime receipt.
- **`device_integrity.py`** — a whole-device receipt script (modeled on
  `browser_runtime_integrity.py`) that snapshots runtime hosts, pinned tools,
  user tools, desktop entries, and policy hashes into a canonical-JSON receipt,
  then verifies the device matches both its receipt and the contract. Subcommands:
  `build`, `verify [--json]`, `metadata-only`.
- **Profile dispatch isolation tests** (32 tests across three layers): plan-mode
  dispatch, bootstrap.sh exit-2 validation, and `validate_target` unit tests via
  sourceable install.sh.
- **Contract-code parity tests**: apt baseline, cloak runtime, macOS GUI casks,
  Node/uv/Bun constants, and USER_TOOLS now cross-checked against the contract.
- **macOS `main()` + BASH_SOURCE guard** on install.sh, mirroring ubuntu/server.

### Changed

- **`ubuntu_apt_packages` contract section restructured**: replaced the
  `essential`/`cli_tools` split (which the code never honored — `clangd` was in
  the code but not in any tier) with `baseline` (31 pkgs) and `cloak_runtime`
  (38 pkgs). `profiles.server` is now `[baseline, cloak_runtime]` — the prior
  `[essential]` was unverifiable and would have failed verify.sh.
- **`gui.macos` synced**: added `ghostty`, renamed `claude-desktop` → `claude`.
- **macOS BUN_LSP_PACKAGES comment corrected**: "kept in lockstep" → accurate
  description (6 of 13; remaining arrive via Homebrew formulae).
- **`device_integrity.py` macOS correctness**: OS-filter on `user_tools` (herdr
  is Linux-only), `dart --version` stderr merge, `gopls` added to RUNTIME_HOSTS,
  tolerant of missing `~/.local/bin` on fresh machines.

### Fixed

- **`verify.sh` now checks `herdr`** in the desktop block — a failed install no
  longer stays invisible.
- **Dead assertion in `test_plan_matrix_is_non_destructive`** removed; replaced
  by meaningful server-vs-desktop dispatch tests (without `--skip-system`).

## [2.4.0] - 2026-08-04

Everything here was found by running the 2.3.0 apply on a real Ubuntu 26.04
desktop. Three independent defects each made the mandatory browser layer
unreachable, so `chrome-devtools-mcp` was never published on a stock supported
host, and rtk is removed by owner decision.

### Removed

- **rtk is no longer installed by this adapter (owner decision).** `install_rtk`,
  its four `supply_chain` pins, the exact-version gates in both verifiers, its
  entry in the managed-shell required commands, and its tests are gone. The apply
  had been failing on it with `managed RTK destination or receipt is invalid`,
  and the refusal was correct: the binary on the reporting host hashed
  `f160611f…` against a contract pin of `ff8a1e77…`, so what was installed was
  never the pinned artifact. Removing the feature removes the mismatch with it.

### Fixed

- **The headless CDP service could not start on any Ubuntu from 23.10 onward.**
  Chromium aborted with `No usable sandbox` (`status=6/ABRT`, seven restarts)
  because 23.10+ restrict unprivileged user namespaces through AppArmor and
  `kernel.apparmor_restrict_unprivileged_userns=1` is stock on 26.04. The Linux
  service now passes `--no-sandbox`; both provenance validators expect it for
  `fingerprint == "linux"` only, because macOS keeps its sandbox and the tail is
  compared exactly. No machine-wide setting was changed - relaxing the kernel
  restriction for every process to fix one headless browser is a far larger blast
  radius for the same outcome. The stealth launcher already passed the flag; only
  the service was missing it.

- **`policy_hashes()` still enforced private mode on Git-tracked sources.** With
  the service up, the apply failed at the integrity contract instead:
  `NOT_PROVEN: path is group/world-writable: scripts/browser_runtime_integrity.py`.
  Git records only the executable bit, so a clone under `umask 002` writes those
  eight files 664 and the gate failed on a pristine tree while `umask 022` hosts
  and CI stayed green. This is the call site the 2.2.0 fix missed. Installed
  runtime paths still fail closed, the checkout is untouched, and the eight files
  are still hashed - which is what actually pins them.

- **A materialized harness checkout inherited the caller's umask.** `git clone`
  under `umask 002` produced 252 group-writable paths, and nddev-codex-app's
  `install-builder` then correctly refused the tree - after the checkout helper
  had reported success. Both the clone path and the fast path now normalize
  through the shared managed-tree helper; the fast path matters most, because it
  is the only one a host with an already-pinned checkout ever takes again.

### Changed

- **The harness layer runs last in both installers.** It delegates to a module
  whose fail-closed guards depend on local state this repository does not own, and
  under `set -euo pipefail` an abort there stranded the language servers, compiled
  hosts, pinned scanners, and browser stack behind it - a desktop missing 24 of
  the 46 commands `verify.sh` required. The step stays fatal; it is now fatal to
  itself rather than to the whole device.

## [2.3.0] - 2026-08-03

Two declared-but-undelivered capabilities are closed in one contract bump: the
`dart-flutter` MCP server had no Dart on any provisioned device, and the zcode
harness step aborted device applies before the layer that installs
`chrome-devtools-mcp`. Both MCP servers named in the `rldyour-mcps` marketplace
were therefore unstartable on a desktop this adapter had just provisioned.

### Added

- **Dart SDK `3.12.2` as the third desktop language-server host (ADR 0006).**
  `rldyour-mcps` declares a `dart-flutter` MCP server whose transport is
  `dart mcp-server`, and `rldyour-claudecode` stated that its Dart SDK pin
  "matches what the bootstrap installs". No bootstrap path installed Dart on
  either platform — the string appeared in this repository only in ADR 0005's
  forbidden list and the test enforcing it — so that MCP server could never start
  on any provisioned device. Ubuntu now installs the stable-channel
  `dartsdk-linux-<arch>-release.zip` into an owned versioned directory with a
  runtime receipt and a managed `~/.local/bin` link, exactly like Go and Rust;
  macOS uses Homebrew's `dart-sdk`. Both digests were confirmed by downloading the
  artifacts (`28e47b44…` x64, `f82c83ec…` arm64). Verification gates on the exact
  (Ubuntu) or floor (macOS) version **and** on `dart mcp-server --version`
  responding, because an SDK that resolves on `PATH` but cannot serve MCP is the
  precise defect this replaces. The Flutter SDK is deliberately excluded: its
  `bin/cache` self-populates at runtime and would mutate a hash-verified tree,
  which needs its own decision rather than a row in this one.
  `dart language-server --protocol=lsp` — the exact invocation `rldyour-lsps`
  declares — was proven against a real `initialize` handshake, with a rejected
  bogus `--protocol` value as the negative control.

- **Dart telemetry disabled through one shared fail-closed helper.** The SDK
  reports by default, which contradicts the boundary that makes the browser
  wrapper reject `--usage-statistics`. `rldyour::ensure_dart_telemetry_disabled`
  runs the SDK's own `dart --disable-analytics` switch — the shared Dart/Flutter
  telemetry config is upstream's to maintain and is never hand-written — then reads
  `reporting=0` back and rejects a conflicting `reporting=1`. Both installers call
  it; Ubuntu's verifier re-proves it.

### Fixed

- **Group-writable directories in the published Dart tree.** The SDK zip records
  directories as `0775`, and umask only clears bits it never adds, so extracting
  under `umask 002` published 113 group-writable directories inside a
  receipt-verified tree. Because the receipt hashes only the declared executables,
  a writable directory beside them was enough to add or swap a snapshot without
  invalidating it. Go and Rust never showed this — their archives store `0755`
  directories. Rather than add a second permission path, the helper written for
  group-writable Bun trees is generalized to
  `rldyour::_managed_tree_permissions` and now normalizes the staged Dart tree
  before the receipt is written and re-validates a reused one.

- **`${RLDYOUR_CODEX_HOME:-$HOME/.codex}/bin` on the managed PATH.**
  `nddev-codex-app` installs its standalone CLI under its own target and publishes
  no link into the managed prefix, while both verifiers required `codex` on
  `PATH`. `rldyour::ensure_path` and the `zshenv` template omitted that directory,
  so strict verification could not pass on a correctly installed device — the
  binary was present and unreachable.

### Removed

- **The zcode harness delegation, entirely (ADR 0006).** The ZCode desktop app
  creates and owns `~/.zcode` on first launch; its module installer then correctly
  refuses to write into an unstamped target without an explicit
  `--adopt-unmanaged`, an adoption decision no unattended run may make for the
  owner. Because `install_ai_runtimes` sat ahead of every other layer under
  `set -euo pipefail`, that refusal aborted whole device applies: an observed
  Ubuntu 26.04 desktop was missing 24 of the 46 commands its own `verify.sh`
  requires — all the bun language servers, Go, Rust, every pinned scanner, the
  entire CloakBrowser stack, and with it `chrome-devtools-mcp`, breaking a second
  declared MCP server for the same reason. `rldyour::install_zcode_harness` and
  `RLDYOUR_ZCODE_MODULE` are removed rather than softened into warn-and-continue,
  which would be exactly the best-effort fallback this repository forbids. zcode is
  declared `harnesses.delegated` in the contract, owned by `nddev-harnesses`, and
  `dependency-check.yml` now fails if any zcode install path returns.

### Changed

- **Every reusable-workflow caller repinned from `0.12.0` to `0.13.3`.** All
  thirteen sat two minor versions behind, so this repository was missing the
  `zizmor-sarif` `actions: read` fix (0.13.2), the `pr-title`
  `pull-requests: read` fix, and the fail-closed guard that stops a privileged
  caller event from supplying `checkout_ref` to `cross-platform-smoke.yml` —
  which this repository calls.

- **The pytest lane installs through hash-locked uv instead of pip.** It ran
  `python -m pip install "pytest==9.1.1"`: pip is forbidden estate-wide, and the
  install was neither hash-verified nor lock-resolved, in the very lane that
  proves the installer. Dependencies now come from a new `requirements-test.txt`
  compiled with `uv pip compile --generate-hashes --universal --python-version
  3.14` and installed with `--require-hashes`. `zsh` stays an apt dependency —
  the terminal-portability suite genuinely needs the shell it asserts about.

### Removed

- **The `windows-latest` leg of `cross-platform.yml`, and its required status
  check.** This adapter targets macOS and Ubuntu; the installers are Bash. The
  lane only asserted that `README.md`, `LICENSE`, `NOTICE` and `VERSION` exist
  and printed `VERSION` — an OS-independent check that could not fail on Windows
  for any reason that would not also fail on the other two runners. It was a
  required check that could not express a real failure, and it billed Windows
  runner minutes on every push, pull request and weekly schedule. The remaining
  two legs keep the metadata contract covered; platform behaviour is proven by
  `ci.yml`, which runs the real installers in plan mode on both supported
  systems.

## [2.2.1] - 2026-08-02

Contract `2.1.0` and `2.2.0` were never published as GitHub releases; both
advanced only the contract and the gitlink the GDS control plane consumes.
This release publishes their combined contents, so the published tag and the
contract agree again.

### Added

- **Eight pinned source-analysis tools that macOS had and Ubuntu did not.**
  Every one is a single upstream release artifact with a tracked
  per-architecture SHA-256, installed into an owned versioned directory with a
  runtime receipt — the same contract as Node, uv, Bun, Go, and Rust. All
  sixteen digests were confirmed by downloading the artifact.

  | Tool | Version | Why Ubuntu needed it |
  | --- | --- | --- |
  | `gitleaks` | `8.30.1` | reproduces the estate's gitleaks CI check locally |
  | `osv-scanner` | `2.4.0` | reproduces the OSV scan |
  | `actionlint` | `1.7.12` | reproduces the workflow lint |
  | `hadolint` | `2.15.1` | 49 Dockerfiles in the estate |
  | `markdown-oxide` | `0.25.12` | Markdown language server; 4218 `.md` files |
  | `delta` | `0.19.2` | see the fix below |
  | `yq` | `4.53.3` | structured YAML editing |
  | `ast-grep` | `0.45.0` | structural search |

  They live in one declarative `PINNED_SOURCE_TOOLS` table driven by a single
  generic installer rather than eight near-identical functions — duplicating
  that contract eight times is how a receipt or a preflight check quietly goes
  missing from one of them. Desktop-only, like the Go and Rust hosts.

  Ubuntu uses `markdown-oxide` where macOS uses `marksman`: marksman's Homebrew
  formula depends on `dotnet@9`, and a .NET runtime is not something this
  adapter should pull onto a desktop. The asymmetry is deliberate and recorded.

  ast-grep's archive also ships an `sg` shim. It is **not** published: upstream
  prints a deprecation banner and exits non-zero, and on a host with util-linux
  it would shadow the setgid `sg`.

### Removed

- **`jdtls` and `kotlin-language-server` from the macOS manifest.** Their
  Homebrew formulae depend on `openjdk` and `openjdk@21`, so installing them
  pulled the JDK that `test_desktop_manifests_exclude_project_runtime_and_docker`
  forbids by name — the ban was satisfied on paper and defeated through
  dependency resolution. The estate has no Java sources, and its only Kotlin
  lives in a Flutter Android app whose toolchain is out of scope here. The test
  now also rejects the known JVM-backed formulae by name.

### Fixed

- **`content_id()` refused Git-tracked sources for a property Git cannot
  carry.** It rejects group- or world-writable inputs, which is genuine tamper
  resistance for a file the installer created and owns. Applied to
  `templates/browser/*`, it instead depended on the umask in force when the
  repository was cloned: a developer whose umask is `002` gets `664` sources and
  failed the gate on a pristine tree, while anyone able to write those files
  could change their contents anyway.

  `content_id()` and `regular_owned()` now take an explicit flag, and
  `cloak_runtime_identity()` — the only caller reading repository sources —
  passes it. Installed runtime paths are unchanged and still fail closed. The
  full suite now passes under `umask 002` and `umask 022` alike.

- **`cmake-language-server` was installed on Ubuntu but never verified,** so a
  failed install stayed invisible while macOS gated on it. It is now required by
  the Ubuntu desktop verifier, along with the eight tools above.

### Added

- **Go and Rust desktop language-server hosts (ADR 0005).** The macOS manifest
  shipped `gopls` while `go` sat in the forbidden set, and Homebrew declares Go
  a *build-only* dependency of that formula — so the Go language server arrived
  without the toolchain it drives and degraded to single-file parsing. Ubuntu
  desktops had neither a Go nor a Rust server at all, while the estate's two
  largest compiled codebases are the control plane's own Go core (451 files,
  verified with `go build ./core/cmd/gds`) and the Rust crates under
  `rldyour-chatgpt`, `nddev-web`, and the Amsterdam captcha WASM.

  Ubuntu now installs Go `1.26.5` from `go.dev/dl` and Rust `1.97.1` from the
  dated `static.rust-lang.org` channel snapshot, both with per-architecture
  SHA-256 values in `config/rldyour-contract.json`, into owned versioned
  directories with runtime receipts and managed `~/.local/bin` links. One
  combined Rust archive per architecture carries rustc, cargo, rust-std, clippy,
  rustfmt, and rust-analyzer, so a single tracked hash covers the host; its
  bundled `install.sh` runs from inside the verified archive. macOS adds `go`,
  `rust`, and `rust-analyzer` through Homebrew. `golang-go`, `rustc`, `cargo`,
  and `rustup` stay forbidden — the managed hosts never come from a distribution
  package.

  gopls `v0.23.0` is pinned by exact module version and verified through the Go
  module checksum database, because it publishes no prebuilt archive;
  `ubuntu_gopls_provenance` records that this is a transparency log rather than
  a tracked hash, so the difference is declared instead of looking like a gap.

  **Desktop only.** `install_compiled_language_hosts` returns early on any
  non-desktop profile. The server profile stays `container-execution-only`:
  project builds and tests run in Docker, and a host compiler there would
  restore exactly the capability that policy removes.
  `tests/test_compiled_language_hosts.py` pins the split, the per-architecture
  hash coverage, installer-to-contract agreement, and the gopls provenance
  declaration.

### Fixed

- **`test_cloak_runtime_identity_preserves_repository_logical_names` could not
  pass under a umask of 002.** The test writes its own fixtures into a pytest
  temporary directory and then feeds them to `content_id()`, which refuses
  group- or world-writable inputs. Under the default umask of a Ubuntu desktop
  those copies arrive `664` and the check failed for a reason unrelated to the
  behaviour under test. The fixtures are now normalized to `644`.

  Note that the repository's *own* `templates/browser/*` files hit the same
  check, and their mode comes from the umask in force when the repository was
  cloned — a property Git does not carry. On a machine with `umask 002` the
  suite still needs those two template files to be non-group-writable.

## [2.0.0] - 2026-07-23

### Changed

- **Advance managed harness pins to their promoted heads:** `nddev-codex-app`
  `dc6db75` → `e8ee019` (config-ownership + overlay-preservation fixes) and
  `nddev-zcode-app` `66f7639` → `4457f07` (source-graph plan/apply collision
  parity), matching the `nddev-harnesses` expected heads.
- **Sync agent-facing docs to the executable contract:** CloakBrowser `0.4.12`,
  Chrome DevTools MCP `1.6.0`, uv `0.11.30` across AGENTS/README/SECURITY/CLAUDE,
  the install and browser-routing docs, and the release-validation memory.
- **uv/bun are the only package managers.** Remove `python3-pip` from the apt
  baseline; publish only the managed `node` launcher (npm/npx/corepack no longer
  on PATH); pin uv/bun source tools; bump uv to 0.11.30.
- **Server profile is `container-execution-only`** (was `server-build-runtime`):
  no host `build-essential`/`pkg-config`; project builds/tests run in Docker.
- **One owner per harness (breaking):** remove the inline Claude Code, OpenCode,
  MiMoCode, Antigravity, and raw ZCode installers; delegate codex and zcode to
  the `nddev-codex-app` / `nddev-zcode-app` modules via `RLDYOUR_CODEX_MODULE` /
  `RLDYOUR_ZCODE_MODULE`.
- **Zsh runtime completed:** SHA-pinned antidote plugins + `zsh-abbr`, offline
  static bundle materialization, starship/atuin/carapace pinned standalone
  artifacts (macOS-parity), opt-in reversible login shell; drop the `mise` shim.
- Bun selects the `x64-baseline` artifact on non-AVX2 CPUs.
- `~/.zshenv.secrets` is no longer sourced by every zsh (agent/secret isolation).

## [1.0.0] - 2026-07-18

First stable release. The module settles its name, reaches a stable adapter
contract, and becomes a first-class GDS module.

### Changed

- Rename the module and adapter identity from `new-mac-or-ubuntu` to
  `macos-ubuntu-bootstrap` across the GitHub repository, the adapter contract
  id, the generated GDS anchor, documentation, scripts, templates, tests, and
  managed drop-in markers. Old repository URLs redirect automatically. Machines
  provisioned under the previous marker keep their existing managed blocks
  until they are re-provisioned under the new marker.

### Added

- Onboard the repository as a GDS-managed module: a schema-validated
  `.gds/repository.yaml` anchor (role `module`, `git-submodule` consumption,
  `github-release` publication) with a bundle-locked compiled policy, while
  preserving the hand-authored `AGENTS.md` as the source of truth.
- The GDS control plane consumes this module as a typed git-submodule, so a
  device provisioned through GDS carries the bootstrap.

### Stable baseline

- Plan-first, idempotent bootstrap for Apple Silicon macOS desktops and Ubuntu
  24.04/26.04 desktops and headless servers, with always-explicit profile
  selection.
- Integrity-pinned AI CLIs, a terminal-first shell (Starship prompt, an
  agent-gated zsh, antidote/atuin/fzf-tab), source and LSP tooling, and a
  hardened loopback-only CloakBrowser runtime with Chrome DevTools MCP and
  Playwright CLI.
- Owner shell files touched only through delimited, backed-up drop-ins; no
  remote-stream-to-shell execution; fail-closed integrity and browser
  boundaries.
- CI wired to the pinned `nddev-ci-workflows` reusable suite: CodeQL, OSSF
  Scorecard, dependency review, secret scan, cross-platform smoke, and
  supply-chain release publication.

## [0.3.10] - 2026-07-10

### Fixed

- Launch Codex through the frozen platform-native binary and isolate package-manager update provenance.

## [0.3.9] - 2026-07-10

### Fixed

- Harden exact legacy CloakBrowser migration, runtime integrity, launchd convergence, signer verification, and scoped non-interactive cmux hooks.

## [0.3.8] - 2026-07-10

### Fixed

- Preserve signed unmanaged macOS app bundles during idempotent cask installation.

## [0.3.7] - 2026-07-10

### Changed

- Adopt the verified Antigravity CLI 1.1.1 runtime and immutable platform artifacts.

## [0.3.6] - 2026-07-10

### Changed

- Retire Webwright fail-closed and remove its checkout, Python environment,
  dependency lock, and CDP overlay. The compatibility command is now an exact
  tombstone wrapper that exits `78` without starting Python or a browser.
- Define Playwright CLI and Chrome DevTools MCP as the only active providers,
  both routed through the fixed managed CloakBrowser endpoint.

### Security

- Reject Playwright CLI `run-code` and `--filename` escape paths that could
  execute arbitrary code outside the managed CDP configuration.
- Publish an owner-only canonical browser runtime receipt that binds exact
  content-addressed runtimes, provider binaries, wrappers, service definition,
  source policies, and rigorous live health; add a standalone full verifier.

### Fixed

- Make macOS and Ubuntu strict verification consume the full browser runtime
  integrity verifier instead of accepting command presence or marker matches.

## [0.3.5] - 2026-07-10

### Fixed

- Restore the standard numeric `workflow_dispatch.inputs.version` release
  path. Manual dispatch now requires the exact `origin/main` commit and its
  successful `bootstrap-gate`, verifies an already existing exact
  non-rewritten tag, and retains the pinned immutable supply-chain publication
  used by numeric tag pushes. Root release automation remains the sole tag
  creator.

## [0.3.4] - 2026-07-10

### Fixed

- Remove the unsupported `args` input from both pinned
  `raven-actions/actionlint` workflow steps. The action's default file
  discovery still validates every workflow without emitting GitHub annotation
  warnings, and regression coverage rejects the unsupported input.

## [0.3.3] - 2026-07-10

### Fixed

- Replace ambiguous `A && B || fallback` control flow in macOS target
  validation and Ubuntu GUI gating with explicit conditionals, and reject that
  pattern across all managed shell scripts before hosted ShellCheck runs.

## [0.3.2] - 2026-07-10

### Fixed

- Make `--skip-system` cover the Ubuntu server baseline and Docker layer so
  validation plans remain non-mutating and independent of hosted-runner Docker
  inventory without weakening normal server plan/apply safety checks.
- Make hosted CI deterministic by using an explicit ShellCheck-safe staging
  predicate, isolating SSH-port tests from the runner's active `ssh.socket`, and
  provisioning Zsh wherever terminal portability tests execute.
- Install ChatGPT and the separate Codex desktop app as independent macOS GUI
  casks while preserving existing cask versions and keeping no-GUI/Linux/server
  profiles free of unsupported Codex app installation.

## [0.3.1] - 2026-07-10

### Fixed

- Provision ripgrep explicitly in hosted validation and release jobs so the
  repository-local fail-closed validator has the same prerequisites as local
  development.
- Replace the obsolete streamed Antigravity-installer CI assertion with checks
  for frozen AI manifest parity, generation-pinned artifacts, and SHA-512 trust
  roots.

## [0.3.0] - 2026-07-10

### Added

- Compose macOS desktop, Ubuntu desktop, and Ubuntu server profiles with an
  explicit GUI overlay and server Docker mode.
- Add non-secret authentication handoff guidance and safe Ubuntu server
  baseline/Docker verification for 24.04 and 26.04.
- Make CloakBrowser the mandatory, health-gated browser boundary for Chrome
  DevTools MCP, Playwright CLI, and Webwright with no stock-browser fallback.
- Add frozen AI CLI/Node-provider/CloakBrowser/Webwright dependency locks and
  immutable, hashed Node.js, uv, Bun, Antigravity, Homebrew, and RTK artifact
  channels; AI package lifecycle scripts remain disabled.

### Changed

- Refresh AI CLI pins for 2026-07-10 and make exact managed packages update
  idempotently instead of accepting any binary already found on `PATH`.
- Restrict desktops to source/LSP tooling; project builds, Docker, and runtime
  execution belong to Ubuntu servers.
- Require explicit Ubuntu role selection and disable Antigravity self-update so
  a verified tool cannot drift outside the tracked contract.
- Install versioned shell drop-ins through backed-up source blocks and verify
  managed PATH, browser, and updater policy in a fresh login shell.
- Guard interactive modern-tool aliases and abbreviations, and select Ubuntu's
  `batcat`/`fdfind` command names without shadowing working core commands.
- Disable all Claude Code update paths and preserve the host's existing
  OpenSSH service-versus-socket activation choice.
- Add tamper-evident Ubuntu Node.js/uv/Bun receipts and managed-link checks;
  preserve installed Homebrew/APT package versions, source-tool versions, and
  healthy Docker workloads instead of implicitly upgrading them on rerun.

### Security

- Preserve conflicting unmanaged configuration, verify repository signing keys,
  never add users to the root-equivalent Docker group, and require explicit
  opt-in for UFW or SSH authentication changes.
- Reject browser trust-root overrides, bind CDP health to the verified binary,
  preserve existing rootful Docker during rootless setup, and roll back failed
  managed UFW changes.
- Run effective SSH-port discovery through a privileged read-only probe and do
  not restart socket-activated listeners for authentication-only hardening.
- Validate SSH keys, accepted algorithms, full Match context, and UFW operator
  CIDR before lockout-sensitive changes; reject multi-primary APT key bundles.

## [0.2.9] - 2026-07-08

### Changed

- Clean release: adopt nddev-ci-workflows 0.3.0 reusable CI and sole-authorship commit policy

## [0.2.8] - 2026-07-08

### Added

- Full Ubuntu LSP parity, gcloud CLI, server/desktop profiles, optional personal apps

## [0.2.7] - 2026-07-08

### Added

- Install the pinned rtk token-economy CLI and exclude-command baseline in the workstation bootstrap

## [0.2.6] - 2026-07-08

### Fixed

- CloakBrowser default privacy-first browser backend across all adapters (ADR 0003).

## [0.2.5] - 2026-07-08

### Fixed

- CloakBrowser default privacy-first browser backend across all adapters (ADR 0003).

## [0.2.4] - 2026-07-08

### Added

- CloakBrowser as the default privacy-first browser backend for every provider.
  Installs the pinned `cloakbrowser==0.4.8` wrapper into an isolated venv,
  downloads and Ed25519-verifies the free-tier Chromium binary, and publishes
  `cloak-chromium` / `cloak-chromium-stealth` launchers. A managed headless CDP
  daemon (launchd on macOS, systemd `--user` on Linux, `KeepAlive`) serves
  `127.0.0.1:9222`; adapter Chrome DevTools MCP connects with `--browserUrl`,
  Webwright/Playwright use the launcher via `AGENT_BROWSER_EXECUTABLE_PATH`.
  Pro (v148+) is opt-in through `CLOAKBROWSER_LICENSE_KEY`; skip the layer with
  `RLDYOUR_SKIP_CLOAKBROWSER=1`.

### Fixed
- CloakBrowser default privacy-first browser backend across all adapters (ADR 0003).
- CloakBrowser daemon on headless Ubuntu servers: enable `systemd` linger
  so the `--user` service boot-starts without an active login session.

- Login-shell PATH precedence: the managed `.zprofile` re-asserts the user
  toolchain directories after macOS `/etc/zprofile` runs `path_helper`, so
  `zsh -l -c` (the Codex/OpenCode agent path) resolves the Homebrew/keg
  toolchain (e.g. `clangd`) instead of the older `/usr/bin` system stubs.

## [0.2.3] - 2026-07-07

### Added

- Terminal layer absorbed from the retired `awesome-terminal-for-ai` spec
  (releases 3.0.0/3.1.0, verdicts of 2026-07-07): shell stack (antidote,
  zsh-completions, olets/tap zsh-abbr, starship, atuin, fzf, zoxide,
  carapace), Ghostty cask, TUIs and CLIs (gh, lazygit, yazi, xh, jaq, jnv,
  duckdb, ast-grep, scc, difftastic, tmux) and the modern-unix introspection
  wave (dust, dua-cli, duf, procs, btop, doggo, gping, hexyl, sd, viddy,
  tealdeer). Ubuntu gets the apt-available subset plus official installers
  for starship/atuin/xh and a git-clone antidote.
- Managed zsh templates (`templates/terminal/`): `.zshenv`/`.zprofile`/
  `.zshrc`/`.zsh_plugins.txt`/`starship.toml` with the agent-neutralization
  gate first; installer never clobbers user-modified files.
- Global git performance keys (core.fsmonitor, core.untrackedCache,
  fetch.writeCommitGraph) and a delta pager config guarded on delta presence.

### Changed

- AI runtime pins: Claude Code 2.1.201 -> 2.1.202, OpenCode 1.17.13 ->
  1.17.14 (npm latest as of 2026-07-07).

### Removed

- `httpie` (dormant upstream; replaced by `xh`), `dasel` and `miller`
  (superseded by jq/yq/DuckDB) from both platform baselines.

### Fixed

- Release workflow: SHA256SUMS now covers every published asset —
  release-notes.md is generated before checksums and the checksum step
  excludes only itself (0.2.2 shipped SHA256SUMS without release-notes.md).

## [0.2.2] - 2026-07-07

### Fixed

- Complete the release-integrity surfaces that `0.2.1` shipped without:
  SECURITY.md supported-versions table and `config/rldyour-contract.json`
  adapter version now track the current exact tag. The `0.2.1` tag was
  published manually and its release carried no build assets (the release
  workflow collided with the pre-created release); `0.2.2` supersedes it
  through the canonical tag-driven workflow with the full asset bundle.

### Changed

- AGENTS.md quality-gate inventory now references the security/SAST scanner
  set through the platform install manifests (positive-inventory wording)
  instead of naming individual scanners in active docs.

## [0.2.1] - 2026-07-07

### Added

- Add `eza` and `bat` to the macOS Homebrew baseline and the Ubuntu profile
  (apt `bat`, exposed as `batcat` on Debian/Ubuntu; `eza` best-effort on older
  LTS archives), with verification coverage on both platforms.

### Fixed

- Verification probed a nonexistent `typescript` binary; the `typescript`
  package ships `tsc`/`tsserver`, so both platform gates now check `tsc`.
  Strict verification could never pass before this fix.

## [0.2.0] - 2026-07-06

### Added

- Expand macOS installer with the full multi-language LSP stack and quality
  gates: basedpyright, ruff, ty, jdtls, kotlin-language-server, gopls,
  postgres-language-server (Supabase), sqls (via `go install`), R languageserver,
  markdown-oxide, terraform-ls, helm-ls, cmake-language-server, oxlint, biome,
  osv-scanner, gitleaks, semgrep, hadolint, actionlint, yamllint,
  markdownlint-cli2, shfmt, and the `fd`, `httpie`, `dasel`, `miller`, `git-delta`,
  `watchexec`, `hyperfine`, `just`, `prettier`, `pandoc`, `kubeconform`, `mise`,
  `libxml2`, `xmlstarlet` utilities.
- Add `qt` headers and `openjdk` to the macOS system baseline so clangd can
  resolve Qt projects and Java/Kotlin LSPs have a runtime.
- Replace `typescript-language-server` with `@vtsls/language-server` (chosen by
  Zed and LazyVim) in both macOS and Ubuntu LSP bundles; add
  `gh-actions-language-server` to both profiles.
- Add Ubuntu extended LSP/quality surface: `default-jdk` and `r-base` runtimes,
  bun-global quality CLIs (`biome`, `oxlint`, `markdownlint-cli2`, `prettier`),
  `sqls` and R `languageserver` (best-effort), and cargo-hosted `gitlab-ci-ls`.
- Add Ubuntu `install_security_scanners()` installing the verify-required
  scanners via their official channels: `basedpyright` (uv tool), `osv-scanner`
  and `gitleaks` (binary install scripts), `semgrep` (pip3), `hadolint` (GitHub
  release binary), and `actionlint` (rhysd download script).
- Extend macOS and Ubuntu `verify.sh` required/optional command sets to cover
  the expanded stack (Java/Kotlin/SQL LSPs, quality gates, utilities) and print
  java/R/clangd runtime versions.
- Document the full dependency matrix in `docs/install.md` across the new
  categories (extended LSPs, quality-gate CLIs, base utilities, JDK/Qt/R,
  Ubuntu security scanners).

### Changed

- Bump adapter contract and README baseline to `0.2.0`; verified_on
  `2026-07-06`.

### Fixed

- Close the macOS/Ubuntu `verify.sh` ↔ `install.sh` contract gaps so strict
  post-checks never fail on a fresh machine: Ubuntu now installs every
  verify-required scanner, and both platforms moved `chrome-devtools-mcp` /
  `playwright-cli` to `optional_cmds` because the browser layer is gated behind
  `--skip-browser`.
- Guard `R --version` in macOS `verify.sh` behind `command -v` so the optional
  R runtime cannot abort verification under `set -euo pipefail`.
- Remove duplicate `ruff` (kept the Homebrew formula as the single source of
  truth, dropped from `PYTHON_TOOLING_PACKAGES`) and duplicate
  `vscode-langservers-extracted` (kept Homebrew, dropped from
  `BUN_LSP_PACKAGES`) on macOS.
- Add `$HOME/go/bin` to `rldyour::ensure_path` so `go install`-built binaries
  like `sqls` are discoverable during verification.
- Align `SECURITY.md` supported-version tag (`0.1.11` -> `0.2.0`), README
  counters (`Scripts: 8`, `Workflows: 11`), and the broken
  `python3 scripts/ci/*.sh` instructions in README (now `bash`).
- Refresh the three Serena memory files to the 2026-07-06 / `0.2.0` baseline.
- Drop the misleading `postgres-language-server` reference from the Ubuntu
  `ensure_cargo_lsps` comment (it never installed it) and the `markdown-oxide`
  entry from the Ubuntu LSP docs (macOS-only install channel).
- shfmt-format `bootstrap.sh` case patterns; ignore `.DS_Store`, `*.swp`,
  `.idea/`, `.vscode/` in `.gitignore`.

## [0.1.11] - 2026-07-04

### Fixed

- Adopt nddev-ci-workflows 0.2.3 and fix reusable CI edge cases.

## [0.1.10] - 2026-07-04

### Fixed

- Migrate CI workflows to nddev-ci-workflows reusable contracts.

## [0.1.9] - 2026-07-04

### Fixed

- Migrate CI workflows to nddev-ci-workflows reusable contracts.

## [0.1.8] - 2026-07-04

### Changed

- CI/CD audit remediation: real actionlint run (antigravity), gitleaks history scan replacing regex (mimocode), digest-pinned gitleaks image (new-mac), CodeQL python+actions matrix with weekly schedule and security-and-quality queries (antigravity/mimocode), job-scoped release permissions, pinned pytest, harden-runner egress audit + persist-credentials on security jobs, strict instruction-docs validation and corrected script path globs (opencode), and stronger branch-protection required checks (new-mac).

## [0.1.7] - 2026-07-04

### Changed

- Align bootstrap doc surfaces (README, AGENTS.md, .claude/CLAUDE.md, docs/install.md) to the Claude Code 2.1.201 installer pin and add an installer-pin/doc parity guard to test_bootstrap_smoke.py so the versions cannot drift silently.

## [0.1.6] - 2026-07-04

### Changed

- Refresh Claude Code runtime pin to 2.1.201 (latest stable) across adapter surfaces and the bootstrap installer.

## [0.1.5] - 2026-07-04

### Fixed

- Align bootstrap smoke tests with the corrected clean-PC install channels.

## [0.1.4] - 2026-07-04

### Fixed

- Install taplo, marksman, pyright, and clangd via working channels so a clean-PC bootstrap and strict verify succeed.

## [0.1.3] - 2026-07-04

### Added

- Install pinned browser providers (Chrome DevTools MCP, Playwright CLI, Webwright) for all adapters.

## [0.1.2] - 2026-07-04

### Fixed

- Synchronize bootstrap contract baseline with released adapter version.

## [0.1.1] - 2026-07-04

### Security

- Refresh GitHub Actions and CodeQL pins across the public module CI surface.

## [0.1.0] - 2026-07-04

### Added

- Added advanced GitHub OSS CI and release hardening for macOS and Ubuntu bootstrap module.
- Added public adapter CI policy-aligned workflow set: `validate`, `actionlint`,
  `codeql`, `dependency-check`, `gitleaks/secret-scan`, `dependency-review`,
  `pytest`, `cross-platform`, `scorecard`, and `release`.
- Added deterministic release pipeline with version checks, SPDX SBOM generation,
  hash manifest, and attestations.
- Added CI smoke tests and baseline `CHANGELOG.md` with release block.

### Fixed

- Fixed Ubuntu installer parity to install `marksman` in the LSP layer, matching
  `verify.sh` contract and macOS behavior.
- Corrected dependency-check and release workflow behavior for pinned runtime validation and SBOM manifest generation.
- Normalized CI workflow hardening artifacts and docs to include full OSS capability set used by module (`validate`, `pytest`, `actionlint`, `codeql`, `gitleaks/secret-scan`, `dependency-review`, `dependency-check`, `cross-platform`, `scorecard`, `release`).
- Synchronized README/docs/security text with actual branch-protection and public repository security controls.
