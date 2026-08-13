# Changelog

All notable changes to this module are documented here. Older release history
remains available in immutable Git tags.

## [Unreleased]

### Added

- Added a canonical machine-readable clean-system support/evidence matrix and
  made hosted evidence fail closed when a required capability is unproven or a
  runner/lane architecture is outside the declared proof boundary.

### Fixed

- Repaired Ubuntu GUI strict verification, which could not pass in any state:
  the Chrome signing-key check was written inside a double-quoted command
  substitution, so its escaped quotes reached `awk` verbatim and the verifier
  aborted under `set -o pipefail`. Vendor-key identity is now one library
  primitive shared by the Chrome and Docker installers and verifiers, and it
  rejects a keyring carrying a second primary key.
- Stopped a failed user tool stranding the layers behind it. Herdr is a user
  tool on every profile, so one divergent Herdr left a server without Docker,
  without the vendor AI CLIs and without verification. Optional-layer failures
  are now reported once, after every layer has been attempted.
- Made plan mode read-only. A plan created `~/.local/bin`, `~/.bun/install/global`
  and `~/.cache/uv` on every Ubuntu profile, and reported a Docker daemon health
  verdict it had never obtained because the probe was routed through the
  dry-run helper.
- Verified every tool the Ubuntu installer publishes. starship, atuin, carapace,
  semgrep, ty, biome, oxlint, markdownlint-cli2, prettier,
  ansible-language-server and gh-actions-language-server were installed on every
  profile and checked by nothing.
- Aligned the desktop layer with its contract: desktop entries follow the
  GUI-capable profile set, the GUI font is a declared package group rather than
  an inline literal, and every managed launcher guards its own program with
  `TryExec`.
- Made the required plan lane exercise the full plan path instead of argument
  parsing alone, and fail if a plan writes to the home directory it describes.
- Removed a Dependabot ecosystem pointing at a directory deleted with the
  browser layer, replaced the release lane's unpinned `pip` install with the
  contract-pinned, SHA-256-verified `uv` path used everywhere else, and repaired
  citations to the two decision records retired in 3.0.0.

## [3.0.1] - 2026-08-13

### Fixed

- Made Herdr permission verification deterministic across BSD/macOS and GNU/Linux
  test hosts, with explicit fail-closed shell control flow and repeat-apply coverage.
- Installed the exact receipt-bound Herdr 0.8.0 macOS release artifact instead
  of accepting the older mutable Homebrew formula.
- Published terminal plugins from verified pinned Git commit trees instead of
  exposing mutable checkout metadata to the executable Antidote source layer.
- Made Ubuntu server verification and device receipts prove the complete
  contract 3.0.1 source-tool set.
- Restricted Ubuntu GUI apply to amd64 because required vendor applications do
  not publish compatible Linux ARM64 builds; ARM64 no-GUI profiles remain
  supported.
- Synchronized release metadata and architecture policy across the contract,
  implementation, tests, ADRs, and operator documentation.

- Updated Herdr to `0.8.0`, with verified macOS and Linux x86_64/aarch64
  installation and verification.
- Updated Telegram Desktop to the official `7.0.9` release and pinned its Linux
  x86_64 archive and source assets to tag commit `a1e89e1f`.
- Declared Herdr on macOS and every Ubuntu profile and Telegram on supported GUI
  targets.

## [3.0.0] - 2026-08-13

### Changed

- Standardized the active AI CLI set on official Codex CLI, Claude Code, and
  Grok Build distributions, with verified installer inputs and `cx`, `cl`, and
  `gk` unrestricted-mode launchers.
- Made Google Chrome stable the sole installed browser.
- Added ChatGPT, Claude, RustDesk, Telegram, Ghostty, and cmux to the applicable
  macOS GUI composition; added Chrome, RustDesk, Telegram, GNOME integration,
  and Firefox removal to Ubuntu GUI.
- Extended Go, Rust, Dart, language servers, terminal tooling, and local static
  verification to the supported profile matrix while retaining explicit
  execution-policy boundaries.
