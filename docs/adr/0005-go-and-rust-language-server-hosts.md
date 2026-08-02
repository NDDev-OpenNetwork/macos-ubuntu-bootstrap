# ADR 0005: Go and Rust as Desktop Language-Server Hosts

- Status: accepted
- Date: 2026-08-02
- Amends: ADR 0004 (desktop `source-lsp-only` execution policy)

## Context

ADR 0004 draws the desktop boundary at source analysis: desktops edit and
inspect code through language servers, while project builds and runtime
execution belong on servers. Contract 2.0.0 enforced that by keeping `go`,
`rustup`, `cmake`, `openjdk`, and Docker out of the desktop manifests, with
`test_desktop_manifests_exclude_project_runtime_and_docker` failing the gate if
any reappeared.

Two facts made that boundary inconsistent in practice.

**The macOS manifest already shipped `gopls` while forbidding `go`.** Homebrew's
`gopls` formula declares Go as a *build-only* dependency, so a bootstrapped
macOS desktop got the Go language server without the toolchain it drives.
`gopls` shells out to `go list` and `go mod` to resolve a module graph; without
`go` on `PATH` it degrades to single-file parsing on exactly the repositories it
was installed for. The capability was declared but not delivered.

**The estate's two largest compiled codebases had no desktop support at all.**
The control plane's own product — `github-device-sync` — is 451 Go files, and
its declared verification commands are `go build ./core/cmd/gds`,
`scripts/validate_go_core.sh`, and `tools/test-sync.sh`. Rust carries
`rldyour-chatgpt` (twelve crates), `server-nddev-kazakhstan/nddev-web`, and the
`server-nddev-amsterdam` captcha WASM. Ubuntu desktops shipped neither a Go nor
a Rust language server, so the estate's maintainer could not read, navigate, or
lint the control plane on a machine this adapter had just provisioned.

The literal reading of ADR 0004 — no compiler on a desktop — was therefore
already violated in spirit by Node, Python, and Homebrew's LLVM, each admitted
as a *tool host* whose presence does not authorize project builds. Go and Rust
are the same shape of dependency and were the only ones excluded.

## Decision

Admit Go and Rust to the desktop profiles as language-server hosts, on the
identical footing as Node, Python, and LLVM.

- **Desktop only.** `install_compiled_language_hosts` returns early on any
  non-desktop profile and logs the reason. The Ubuntu server profile stays
  `container-execution-only`: project builds and tests run in Docker, and a host
  compiler there would restore precisely the capability that policy removes.
- **Tracked provenance, never distribution packages.** Ubuntu installs Go from
  `go.dev/dl` and Rust from the dated `static.rust-lang.org` channel snapshot,
  both with per-architecture SHA-256 values recorded in
  `config/rldyour-contract.json`, into owned versioned directories with runtime
  receipts and managed `~/.local/bin` links. `golang-go`, `rustc`, and `cargo`
  remain forbidden apt packages. macOS uses Homebrew, consistent with every
  other macOS tool.
- **One archive covers the Rust host.** The combined `rust-<version>-<triple>`
  tarball carries rustc, cargo, rust-std, clippy, rustfmt, and rust-analyzer, so
  a single tracked hash covers the whole host. Its bundled `install.sh` runs
  from inside the hash-verified archive — a verified artifact, not remote code
  piped to a shell.
- **gopls provenance is different and stays explicit.** gopls publishes no
  prebuilt archive. It is pinned to an exact module version and verified through
  the Go module checksum database (`sum.golang.org`) with `GOFLAGS=-mod=readonly`;
  `ubuntu_gopls_provenance` records that this is a transparency log rather than
  a hash this repository tracks, so the gap is declared rather than looking like
  a missing entry in the hash table.

The execution policy string stays `source-lsp-only`. What changed is the list of
hosts that policy admits, not the policy itself.

## Consequences

**What this gives up.** A desktop now has `go build` and `cargo build`
available. The boundary between "source analysis" and "local project build" on
desktops is now intent and documentation, not absence of a compiler — the same
weaker guarantee that already applied to Node and Python. Anyone who wants the
strong version must remove the hosts and accept losing gopls and rust-analyzer
with them.

**What it costs.** Roughly 1.4 GB of managed toolchain per desktop, and two more
version pins to advance when upstream moves. Both are covered by the existing
receipt and preflight machinery, so a tampered or unmanaged destination still
fails closed.

**What stays enforced.** Docker, `cmake`, `openjdk`, `dart`, `deno`, `mise`,
`cargo-nextest`, and `rustup` remain out of desktop manifests, and the server
profile still receives no host compiler. `test_compiled_language_hosts.py` pins
the desktop/server split, the per-architecture hash coverage, the
installer-to-contract agreement, and the declared gopls provenance.
