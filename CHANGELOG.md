# Changelog

All notable changes are documented here. The project follows Semantic
Versioning; the contract version in `config/rldyour-contract.json` moves with it.

## [Unreleased]

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
