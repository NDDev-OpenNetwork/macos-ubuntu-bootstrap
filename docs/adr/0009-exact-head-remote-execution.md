# ADR 0009: Exact-HEAD Remote Execution

- Status: Accepted
- Date: 2026-08-10
- Amends: ADR 0004

## Context

The estate needs both full Ubuntu workstations that build locally and lighter
Ubuntu/macOS workstations used for source editing, agent work and language
servers. The latter still need a reproducible path to builds and tests on a
provisioned Ubuntu server. Copying a dirty worktree or evaluating a remote
shell string would make the executed input ambiguous and would mix source
synchronization, credentials and execution into one unsafe operation.

## Decision

Keep the existing profiles and ownership boundaries:

- `desktop` is the source/LSP client;
- `desktop-builds` performs local Docker builds;
- `server` is the container execution host.

`scripts/remote-exec.sh` connects a `desktop` to a `server` only when both
repositories are clean and resolve to the same exact Git commit. Host, remote
repository and command argv are explicit. The adapter does not copy source,
repair Git state, materialize SSH credentials or evaluate a command string.

## Consequences

Remote execution is reproducible and auditable by commit identity. Uncommitted
experiments must be committed to a branch before execution. Provisioning the
server checkout and SSH identity remains a separate owner-controlled operation.
If either side drifts, execution stops before the requested command starts.
