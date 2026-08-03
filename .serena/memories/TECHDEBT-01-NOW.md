<!-- Memory Metadata
Last updated: 2026-08-04
Last verified: 2026-08-04
Last commit: 47b1b549bb55830f839834ef33bac41a5f278a69 feat(rtk)!: remove rtk from the bootstrap (2.4.0)
Scope: .gitignore, .serena/project.yml, README.md, AGENTS.md, .claude/CLAUDE.md, scripts/**
Area: TECHDEBT
-->

# TECHDEBT-01-NOW

## Scope
Operational watchpoints and boundaries for the bootstrap module.

## Applies to
- `.gitignore`
- `.serena/project.yml`
- `.serena/memories/**`
- `README.md`
- `AGENTS.md`
- `.claude/CLAUDE.md`
- `scripts/**`

## Source of truth
- `.gitignore`: durable context and runtime-local ignore boundaries.
- `.serena/project.yml`: Serena module activation metadata.
- `README.md`: public module scope and repository-context contract.
- `AGENTS.md` and `.claude/CLAUDE.md`: CLI-specific instruction surfaces.
- `scripts/**`: actual bootstrap and verification behavior.

## Invariants
- Do not commit runtime markers, caches, diagnostics, traces, local env files, browser artifacts, credentials, or generated junk.
- Do not hide durable Serena memory files behind `.gitignore`.
- Keep bootstrap runtime ownership separate from adapter-native browser task routing.
- Keep README, AGENTS, and CLAUDE docs aligned with actual scripts and workflow names.

## Current State
- Durable Serena memory files are tracked; runtime-local Serena state remains ignored.
- The module owns installation and verification, not adapter-native MCP, command, skill, or task-routing surfaces.
- Managed shell integration edits only delimited source blocks, backs up pre-existing files, and verifies a fresh login shell. Interactive aliases activate only when their target executable exists.
- rtk is out of bootstrap scope as of `2.4.0` by owner decision: not needed, and bootstrap must not install it. `install_rtk`, the four `supply_chain` rtk_* pins, both verifier gates, and its managed-shell requirement are gone. Recorded because the removal also resolved a real provenance mismatch: the binary installed on the owner desktop hashed `f160611f...` against a contract pin of `ff8a1e77...`, so what was there had never been the pinned artifact.
- The browser layer could not come up on ANY Ubuntu from 23.10 onward before `2.4.0`: those releases restrict unprivileged user namespaces through AppArmor (`kernel.apparmor_restrict_unprivileged_userns=1` is stock on 26.04), and the managed headless service passed no `--no-sandbox`, so Chromium aborted with `status=6/ABRT`. The flag is Linux-only; macOS keeps its sandbox and the provenance validators compare the argument tail exactly. The kernel setting is deliberately left enabled.
- `policy_hashes()` in `browser_runtime_integrity.py` was the call site the `2.2.0` umask fix missed: it enforced private mode on eight Git-tracked sources, so a clone under `umask 002` failed the gate on a pristine tree while `umask 022` and CI stayed green. Installed runtime paths still fail closed. If this shape reappears, look for a dropped `repository_sources` / `enforce_private_mode` argument; do not weaken the installed-path check and do not chmod the checkout.
- A materialized harness checkout inherits the caller's umask, so `git clone` under `umask 002` produced 252 group-writable paths and nddev-codex-app's `install-builder` refused the tree after the checkout helper had reported success. `rldyour::_harness_checkout_permissions` now normalizes on both the clone path and the fast path; the fast path is the only one an already-pinned host takes again.
- Known local blocker on the owner desktop, not a module defect: `~/.codex/nddev-builder.config.toml` points its marketplace at `nddev-codex-app-patched`, so the codex module refuses to overwrite it and the harness layer fails at the end of an apply. Since `2.4.0` the harness layer runs last, so this no longer strands any other layer.
- ZCode is out of bootstrap scope as of `2.3.0` (ADR 0006). The app creates and owns `~/.zcode` on first launch and its module installer refuses an unstamped target without an explicit `--adopt-unmanaged`, which no unattended run may supply; because the harness step ran ahead of every later layer under `set -euo pipefail`, that refusal aborted whole device applies. It is declared `harnesses.delegated` with `nddev-harnesses` as owner.
- A real Apple Silicon macOS desktop strict apply and an immediate non-interactive idempotent reapply were verified on 2026-07-10, including managed launchd/CDP health and cmux hooks. Representative Ubuntu 24.04/26.04 desktop/server runs with systemd, SSH/UFW, and each selected Docker mode remain required; container-only CI cannot prove those host boundaries.
- No current bootstrap contract/version drift: `VERSION`, contract, scripts, frozen locks, docs, SECURITY, and tests agree on `2.4.0` and its exact runtime pins. `2.2.1` remains the published release tag: `2.3.0` and `2.4.0` are contract-only so far, the same shape as the unreleased `2.1.0` and `2.2.0` before them.
- Release `2.2.1` publishes the combined contents of the unreleased `2.1.0` and `2.2.0` contracts. The published tag trails the contract again at `2.4.0`, which is the module's normal shape between releases, not drift.
- Resolved in `2.2.0`: `content_id()` and `regular_owned()` now take an explicit flag, and `cloak_runtime_identity()` — the only caller reading Git-tracked sources — passes it. The suite passes under `umask 002` and `umask 022` alike. Installed runtime paths still fail closed on a group- or world-writable file, pinned by `test_private_mode_is_enforced_for_installed_files_and_not_for_sources`.
- Historical Webwright runtimes may remain on previously configured devices for preservation, but no managed command, dependency, or config path can execute them.

## Evidence
- path:.gitignore
- path:.serena/project.yml
- path:README.md
- path:AGENTS.md
- path:.claude/CLAUDE.md
- path:scripts/macos/install.sh
- path:scripts/ubuntu/install.sh
- path:scripts/lib/common.sh
- path:scripts/ubuntu/server.sh
- path:tests/test_transactional_runtime.py
- path:tests/test_ubuntu_server_safety.py
- commit:911265b
- commit:0ec6ec6
- commit:ec5416b
- commit:03419cc
- commit:c7fc734
- commit:7b31369
- commit:0ea9b5b
- commit:8631dd0

## Do Not Infer
- Do not infer full workstation installation success from plan-mode scripts; strict verification and optional runtime checks must run on the target machine.

## Update Triggers
- Update when ignore rules, instruction docs, Serena paths, installer layers, or bootstrap-only boundaries change.

## Validation Commands
- `git check-ignore -v .serena/.sync_marker`
- `git check-ignore -q .serena/memories/CORE-01-INDEX.md`
- `bash scripts/ci/validate.sh`
- `python3 -m pytest -q`
- `shellcheck scripts/lib/common.sh scripts/ubuntu/server.sh scripts/ubuntu/verify-server.sh`

## Repair Procedure
- Restore durable memory tracking, keep runtime state ignored, align docs with scripts, then rerun validation commands.

## Update policy
Keep this memory focused on current operational boundaries and verified technical debt only.
