# ADR 0006: Dart as a Desktop Host, and zcode Delegated Out of Bootstrap

- Status: accepted
- Date: 2026-08-03
- Amends: ADR 0005 (Go and Rust as desktop language-server hosts)

## Context

Two independent defects were found on a real Ubuntu 26.04 desktop that this
adapter had provisioned. Both had the same shape: a capability was declared
somewhere in the estate and delivered nowhere.

**`dart` was declared by the MCP marketplace and forbidden by this adapter.**
`rldyour-mcps` ships a `dart-flutter` MCP server whose transport is
`dart mcp-server`, and `config/mcp-runtime-versions.env` in `rldyour-claudecode`
stated that Dart SDK 3.12.2 "matches what the rldyour-new-mac-or-ubuntu bootstrap
installs". No bootstrap path installed Dart on either platform: the string `dart`
appeared in this repository only in ADR 0005's list of things that stay
forbidden, and in the test that enforces it. The marketplace server could
therefore never start on any device this adapter provisioned. The companion claim
that `scripts/bootstrap_check.sh` enforced a Dart 3.9+ gate was also false — that
script checks `python3`, `git`, and `node`.

**The zcode harness made every layer behind it unreachable.** `install.sh` runs
`set -euo pipefail`, and `install_ai_runtimes` — which delegated to
`nddev-zcode-app` — sat ahead of the language servers, the compiled hosts, the
pinned scanners, the browser stack, and rtk. The ZCode desktop app creates and
owns `~/.zcode` on first launch. Its module installer correctly refuses to write
into an unstamped target and demands an explicit `--adopt-unmanaged`. So on any
device where the app had ever been launched, a full `--apply` aborted at the
harness step and installed nothing after it. The observed result was a desktop
missing 24 of the 46 commands its own `verify.sh` requires, including
`chrome-devtools-mcp` — so a second declared MCP server was broken by the same
abort.

## Decision

**Admit Dart as a desktop host, on the identical footing as Go and Rust.**

- One self-contained artifact. The stable-channel
  `dartsdk-linux-<arch>-release.zip` carries `dart language-server` (the analysis
  server) and `dart mcp-server` (the marketplace transport), so a single tracked
  SHA-256 covers both capabilities. Ubuntu installs it into an owned versioned
  directory with a runtime receipt and a managed `~/.local/bin` link, exactly like
  Go and Rust. macOS uses Homebrew's `dart-sdk`, consistent with every other
  macOS tool.
- Desktop only. `install_compiled_language_hosts` returns early on the server
  profile, which stays `container-execution-only`.
- The Flutter SDK is deliberately **not** installed. `dart mcp-server` runs from
  the Dart SDK alone and discovers a Flutter SDK through `FLUTTER_SDK` when one
  exists. Flutter's `bin/cache` self-populates on first invocation, which would
  mutate a hash-verified runtime directory and break the receipt contract that
  makes every other managed host tamper-evident. Adding Flutter therefore needs
  its own decision about where a mutable cache may live, not a row in this one.
- Verification proves the subcommand, not just the binary. Both platform
  verifiers gate on the exact (Ubuntu) or floor (macOS) version *and* on
  `dart mcp-server --version` succeeding. An SDK that resolves on `PATH` but
  cannot serve MCP is the exact failure this ADR exists to prevent, so
  presence-only checking would reproduce it.
- **Permissions are normalized, because this archive needs it.** The SDK zip
  records its directories as `0775`, and a umask cannot save the tree — umask only
  clears bits it never adds. Extracting under `umask 002` publishes 113
  group-writable directories inside an otherwise receipt-verified tree, and the
  receipt hashes only the declared executables, so anyone in the owner's group
  could add or replace a snapshot beside them without invalidating it. Go's and
  Rust's archives store `0755` directories and never showed this. The fix reuses
  the permission helper written for group-writable Bun trees rather than adding a
  second path: it is renamed `rldyour::_managed_tree_permissions`, normalizes the
  staged tree before the receipt is written, and re-validates a reused tree.
- **Telemetry is disabled, and proven disabled.** The Dart SDK reports by default.
  A bootstrap-installed SDK that phones home would contradict the same boundary
  that makes the browser wrapper actively reject `--usage-statistics`. The opt-out
  is set through the SDK's own `dart --disable-analytics` switch, never by writing
  the shared Dart/Flutter telemetry config by hand — that file is upstream's to
  maintain. One helper serves both platforms, and it fails closed: the installer
  reads `reporting=0` back and rejects a conflicting `reporting=1` instead of
  reasoning about upstream duplicate-key precedence. Ubuntu's verifier re-proves
  it; macOS keeps its documented weaker-gate posture.

ADR 0005's closing list is amended: `dart` moves from "stays enforced" to an
admitted host. `cmake`, `openjdk`, `deno`, `mise`, `cargo-nextest`, `rustup`, and
Docker are unchanged, and distribution packages for the hosts stay banned — the
`dart` **apt** package remains forbidden, because the managed SDK is installed
from a tracked artifact and never from a distribution repository.

**Delegate zcode out of bootstrap entirely.**

- `harnesses.active` is exactly `["codex"]`. zcode moves to
  `harnesses.delegated`, which records `nddev-harnesses` as its owner repository
  and the reason it cannot be installed unattended.
- `rldyour::install_zcode_harness` is removed rather than made non-fatal. A
  best-effort harness step that logs a warning and continues would be the
  "weaken a mandatory check into best-effort" pattern this repository forbids;
  the honest form is that bootstrap does not own this harness.
- Neither verifier requires `zcode` any more, and
  `rldyour::verify_terminal_environment` no longer conditions on
  `RLDYOUR_ZCODE_MODULE`.

**Publish `codex` where it can actually be found.** `nddev-codex-app` installs
its standalone CLI under its own target (`~/.codex/bin/codex`) and publishes no
link into the managed prefix, while both verifiers required `codex` on `PATH`.
`rldyour::ensure_path` and the managed `zshenv` template now include
`${RLDYOUR_CODEX_HOME:-$HOME/.codex}/bin`, so strict verification can pass on a
correctly installed device. Before this change it could not pass at all.

## Consequences

**What this costs.** Roughly 650 MB of managed Dart SDK per desktop across the
two architectures, one more version pin to advance, and one more artifact whose
digest must be confirmed by download when it moves.

**What this gives up.** A desktop now has `dart compile` and `dart run`
available. This is the same weakened boundary ADR 0005 already accepted for Go
and Rust: on desktops the line between source analysis and local project build is
intent and documentation, not the absence of a toolchain.

**What zcode delegation gives up.** A single `bootstrap.sh --apply` no longer
produces a device with ZCode on it. That is the intended trade: the previous
behavior did not produce one either, it just failed loudly at that point and
silently skipped everything after. Devices that want ZCode get it from
`nddev-harnesses`, which owns the adopt decision the operator has to make.

**What stays enforced.** The server profile still receives no host toolchain.
`test_compiled_language_hosts.py` pins the desktop/server split, the
per-architecture hash coverage, and installer-to-contract agreement for Dart on
the same terms as Go and Rust. `scripts/ci/validate.sh` fails if the active
harness set drifts from `["codex"]` or if the zcode delegation loses its declared
owner or reason.
