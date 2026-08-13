# Verified dependency source register

`config/rldyour-contract.json` is the machine-readable authority for dependency
identity. This page records the human-auditable source decision; installers and
verifiers duplicate only shell constants that parity tests bind back to the
contract.

## Herdr 0.8.0

Verified 2026-08-13 against the official
[v0.8.0 release](https://github.com/herdrdev/herdr/releases/tag/v0.8.0), the
[GitHub releases feed](https://github.com/herdrdev/herdr/releases.atom), and the
[upstream update manifest](https://herdr.dev/latest.json). During hosted
Attempt 2 earlier that day, the stable Homebrew formula still installed 0.7.5;
it subsequently caught up to 0.8.0. That interval was normal downstream
packaging lag, not runner or network failure. A downstream formula cannot prove
the product's exact artifact identity even after its version catches up, so
bootstrap installs immutable upstream release assets directly:

The annotated `v0.8.0` tag object is
`857196dee1ce98df53efdd3f437aa2ac8a75b608` and resolves to commit
`346411fa21afd297f5ed3b3fa56f9e3fbf7654b7`. The upstream tag is unsigned, so
asset identity is fail-closed on the independently verified SHA-256 values below.

| Target | Official asset | SHA-256 |
|---|---|---|
| macOS Apple Silicon | `herdr-macos-aarch64` | `d53a9f93fccfdfcc55632927bf51002f5add0aa7990bcdf508ffbd84ac658178` |
| Linux x86_64 | `herdr-linux-x86_64` | `b872ea7e40fa2cb17e857ac9b62b1bf26db7b403c622f5d2f3f5b35f6e9acd28` |
| Linux aarch64 | `herdr-linux-aarch64` | `f647ac66468d9efbc642fe534fb284468f0aea60641606fc008dfc0d82a3ca87` |

The live upstream manifest is evidence for source discovery and update PRs only;
installation never resolves `latest` and uses only the exact tag URLs and hashes
stored in the contract. Bootstrap also never invokes `herdr update`; version
changes arrive through reviewed update PRs that refresh the tag, commit, asset
URLs, hashes, tests, and this register together.
