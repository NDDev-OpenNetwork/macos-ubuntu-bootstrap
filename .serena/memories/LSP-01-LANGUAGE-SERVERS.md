<!-- Memory Metadata
Last updated: 2026-08-03
Last verified: 2026-08-03
Last commit: 4ceac2921743308354b4292034e12e6400ad3e6d Merge pull request #40 from NDDev-it-com/feat/dart-host-and-zcode-delegation
Scope: language-server setup and diagnostic proof
Area: LSP
-->

# Language Server Quality Gates

## Scope
language-server setup and diagnostic proof

## Current source of truth
- `path:scripts/ubuntu/install.sh`
- `path:scripts/macos/install.sh`
- `path:config/rldyour-contract.json`
- `path:docs/adr/0005-go-and-rust-language-server-hosts.md`
- `path:tests/test_compiled_language_hosts.py`

## Last verified
- date: 2026-08-02
- commit: `644384032ffff1f0f9dc11f0600e45f662f2b48c`
- checked by: verified against current code, contract, and passing gates

## Facts
- Desktop profiles install source-editing and language-server tooling; project build execution belongs on servers.
- Contract `2.1.0` (ADR 0005) admits Go `1.26.5` and Rust `1.97.1` as desktop-only language-server hosts for `gopls` and `rust-analyzer`, on the same footing as Node, Python, and Homebrew's LLVM: present to resolve source, not to authorize project builds.
- Contract `2.3.0` (ADR 0006) admits the Dart SDK `3.12.2` on the same footing, and it carries two capabilities: `dart language-server --protocol=lsp` (the invocation `rldyour-lsps` declares, proven against a real `initialize` handshake) and `dart mcp-server`, the transport the `dart-flutter` MCP server in `rldyour-mcps` executes. Before `2.3.0` no bootstrap path installed Dart on either platform while the marketplace claimed otherwise, so that MCP server could never start.
- The Dart SDK zip records its directories as `0775` and umask only clears bits it never adds, so the staged tree passes `rldyour::_managed_tree_permissions normalize` before its receipt is written and a reused tree is re-validated. That helper is the generalized former browser-Node one; adding a second permission path is forbidden.
- Dart telemetry is disabled through `rldyour::ensure_dart_telemetry_disabled`, which runs the SDK's own `--disable-analytics` switch and then reads `reporting=0` back from the shared Dart/Flutter telemetry config. Never hand-write that file: upstream maintains it. Ubuntu's verifier re-proves the opt-out; macOS keeps its documented weaker-gate posture.
- The Flutter SDK is deliberately not installed: its `bin/cache` self-populates at runtime and would mutate a hash-verified tree.
- Ubuntu installs both from tracked per-architecture SHA-256 artifacts into owned versioned directories with runtime receipts; `golang-go`, `rustc`, `cargo`, and `rustup` remain forbidden distribution packages. macOS uses the `go`, `rust`, and `rust-analyzer` Homebrew formulae.
- One combined `rust-<version>-<triple>` archive carries rustc, cargo, rust-std, clippy, rustfmt, and rust-analyzer, so a single tracked hash covers the whole Rust host.
- `gopls` `v0.23.0` is the one host component without a tracked archive hash: it publishes no prebuilt archive, so it is pinned by exact module version and verified through the Go module checksum database. `runtime_support.ubuntu_gopls_provenance` records that class explicitly.
- `install_compiled_language_hosts` returns early on any non-desktop profile. The Ubuntu server profile stays `container-execution-only` and receives no host compiler.
- Contract `2.2.0` adds eight pinned source-analysis tools to Ubuntu desktops via the declarative `PINNED_SOURCE_TOOLS` table and one generic installer: gitleaks `8.30.1`, osv-scanner `2.4.0`, actionlint `1.7.12`, hadolint `2.15.1` (the four that reproduce the estate's CI checks locally), plus markdown-oxide `0.25.12`, delta `0.19.2`, yq `4.53.3`, ast-grep `0.45.0`. Adding a tool means adding a row; there is no second install path.
- Ubuntu uses markdown-oxide where macOS uses marksman, because marksman's Homebrew formula depends on `dotnet@9`. ast-grep's `sg` shim is never published: upstream deprecated it and it would shadow util-linux's setgid `sg`.
- `terraform-ls` and `helm-ls` stay macOS-only by decision: the estate contains no Terraform and no Helm charts.
- `jdtls` and `kotlin-language-server` were removed from macOS: their formulae depend on `openjdk` / `openjdk@21`, so they pulled the JDK the manifest forbids by name.

## Evidence
- `commit:25e5b7bbf07ca90192022ac8fb9f300d443b9410`
- `path:README.md`

## Known pitfalls
- Treat this memory as derived context. Current code, configuration, runtime output, and GitHub state override stale memory text.

## Update policy
Update after verified changes to the referenced source-of-truth files.

## Delete / merge policy
- Delete or merge only when the referenced source-of-truth files no longer support this memory and the replacement memory preserves the durable facts.

## Applies to

- The scope and source-of-truth paths declared in this memory.

## Source of truth

- The `Current source of truth` entries above, plus current code, configuration, tests, git state, and live GitHub state where this memory references live release or repository surfaces.

## Invariants

- Current code, configuration, tests, validators, git state, and live GitHub state override this memory whenever they disagree.

## Current State

- Treat the `Facts` section as the current durable state. Do not treat historical evidence, superseded notes, or previous release entries as current.

## Do Not Infer

- Do not infer runtime versions, product versions, commits, permissions, release state, security posture, or tool behavior from this memory without checking the source of truth.

## Update Triggers

- Update after verified changes to the source-of-truth files, runtime baselines, release tuple, validation gates, live release state, or durable agent-workflow contracts.

## Validation Commands

- Run the rldyour control-plane Serena memory validators in strict mode: `validate_serena_memory_schema` (`--strict-mode strict-all`) and `validate_serena_memory_semantics` (`--strict-current-facts --strict-metadata-dates --strict-evidence-commits`).

## Repair Procedure

1. Re-read the source-of-truth files listed above.
2. Update only verified current facts; move stale facts into historical evidence.
3. Rerun the validation commands until green.
