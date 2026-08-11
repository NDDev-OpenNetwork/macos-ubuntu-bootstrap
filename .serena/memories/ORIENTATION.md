<!-- Memory Metadata
Last updated: 2026-08-12
Scope: pointer to the canonical sources; carries no pins and no policy
Area: ORIENTATION
-->

# Orientation

This is a map, not a source of truth. Every fact below is owned by a file; read
that file rather than trusting this one.

## What this module is

A plan-first bootstrap and verification adapter for Apple Silicon macOS
desktops and Ubuntu 24.04/26.04 desktops, desktop-builds workstations and
headless servers. It is an adapter, not an upstream runtime.

## Where each kind of fact lives

| Looking for | Read |
| --- | --- |
| Mission, profiles, boundaries, commands | `AGENTS.md` |
| Exact versions, digests, ownership, profile matrix | `config/rldyour-contract.json` |
| Why a boundary exists | `docs/adr/` |
| What a script does | the script under `scripts/` |
| Whether a rule holds | run its check; do not read prose |
| User-visible history | `CHANGELOG.md` |
| Operator procedure | `README.md`, `docs/install.md` |
| Threat posture | `SECURITY.md` |

## Why there is only one memory here

There were 23. Together they held about forty lines of fact inside seventeen
hundred lines of identical scaffolding, every fact restated one of the files
above, and several had gone quietly wrong: the index claimed three tracked
memories, one described a cmux integration for two harnesses this module had
already stopped installing, and the recorded contract version was two releases
stale. Deleting them lost nothing — each fact was checked against the sources
first, and every one was already recorded in a code comment, a changelog entry
or an ADR.

Add a memory here only for something durable that no source file can own. A
rule that can be checked belongs in a test; a decision belongs in an ADR; a
version belongs in the contract.
