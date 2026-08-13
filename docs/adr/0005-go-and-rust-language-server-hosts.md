# ADR 0005: Compiled-language hosts for source analysis

- Status: accepted
- Date: 2026-08-02
- Amended: 2026-08-13 by contract 3.0.1

## Context

`gopls`, `rust-analyzer`, and the Dart analysis server need their matching SDKs
to resolve real projects. Installing only the language-server executable leaves
source navigation incomplete. The Dart SDK also supplies `dart mcp-server`.

## Decision

Install receipt-verified Go, Rust, and Dart hosts on every Ubuntu profile and
use Homebrew-managed hosts on macOS. Pin versions and per-architecture hashes in
the machine-readable contract. Install `gopls` at an exact module version through
the Go checksum database because it has no upstream binary archive.

These hosts authorize source analysis and local static verification. They do
not change the profile execution policy: plain desktop remains
`source-lsp-only`, desktop-builds explicitly allows local Docker builds/tests,
and server remains `container-execution-only` for project execution.

## Consequences

- Every profile can resolve Go, Rust, and Dart sources consistently.
- The server verifier and device-integrity receipt must prove the exact hosts,
  pinned source tools, Dart MCP transport, and the successful documented
  `dart --disable-analytics` opt-out. The unified-analytics config file is an
  optional upstream diagnostic: CI may suppress analytics without materializing
  it, so absence is observed but does not invalidate an installation.
- A compiler being present is not permission to run project builds outside the
  profile policy; server project execution stays in Docker.
