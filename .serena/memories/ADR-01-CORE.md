<!-- Memory Metadata
Last updated: 2026-08-04
Last verified: 2026-08-04
Last commit: 47b1b549bb55830f839834ef33bac41a5f278a69 feat(rtk)!: remove rtk from the bootstrap (2.4.0)
Scope: architecture decisions and owner-approved policy changes
Area: ADR
-->

# ADR Core

## Scope
architecture decisions and owner-approved policy changes

## Current source of truth
- `path:docs/adr`

## Last verified
- date: 2026-08-02
- commit: `881c07ad415e6ac11052cfe01ab088de92de810d`
- checked by: verified against current code, contract, and passing gates

## Facts
- Bootstrap architecture or policy meaning changes require explicit owner approval; implementation-only maintenance must preserve the current decisions.
- ADR 0004 (accepted 2026-07-10) fixes profile composition and the CloakBrowser boundary.
- ADR 0006 (accepted 2026-08-03) amends ADR 0005: the Dart SDK joins Go and Rust as a desktop language-server host, which also makes the `dart-flutter` MCP transport available, and the zcode harness is delegated out of bootstrap to `nddev-harnesses` because its target cannot be adopted unattended. ADR 0005 had listed `dart` among the things that stay forbidden; the `dart` apt package still is.
- ADR 0005 (accepted 2026-08-02) amends ADR 0004: Go and Rust join Node, Python, and LLVM as desktop language-server hosts. It is explicit that this trades away the strong form of the desktop boundary — the separation between source analysis and local project build becomes intent and documentation rather than absence of a compiler, the same weaker guarantee that already applied to Node and Python.

## Evidence
- `commit:25e5b7bbf07ca90192022ac8fb9f300d443b9410`
- `path:docs/adr`

## Known pitfalls
- Treat this memory as derived context. Current code, configuration, runtime output, and GitHub state override stale memory text.

## Update policy
ADR meaning changes require explicit owner approval; format-only normalization may be done without changing the decision.

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
