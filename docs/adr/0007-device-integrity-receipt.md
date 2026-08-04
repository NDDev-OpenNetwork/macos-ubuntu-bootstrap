# ADR 0007: Whole-Device Integrity Receipt

- Status: accepted
- Date: 2026-08-04

## Context

The browser runtime has had an integrity receipt (`browser_runtime_integrity.py`)
since contract 2.4.0: a canonical-JSON snapshot that is built from a proven
installed state, persisted atomically, and verified by re-collecting state and
comparing exactly. This closes the tamper/drift gap for the browser stack.

No equivalent existed for the rest of the device. `verify.sh` compares installed
runtime versions against **hardcoded bash literals** (`v24.18.0`, `1.3.14`,
etc.), not against `rldyour-contract.json`. The contract and the installer can
drift silently: bump one, forget the other, and no check fails until a real
device receives a version it was not expecting.

The gap was exposed when `device_integrity.py` (contract 2.5.0) first ran on the
reference desktop: `gopls` was declared in the contract as `v0.23.0` but the
installed binary reported `0.23.0` — the `v` prefix mismatch was invisible to
every existing check.

## Decision

Introduce a **whole-device integrity receipt** that mirrors the browser receipt's
architecture and extends it with a contract-comparison layer.

### Receipt schema

`device_integrity.py` builds a canonical-JSON receipt at
`~/.local/share/rldyour/device-receipt.json` (mode `0600`, atomic write via
`O_CREAT|O_EXCL` + `fsync`). The receipt contains:

- `schema`: `rldyour-device-receipt-v1`
- `owner`: `macos-ubuntu-bootstrap`
- `bootstrap_version`: receipt-schema version (separate from the adapter
  contract version — a receipt survives a contract bump that does not change
  the receipt shape)
- `home`: the user's home directory (the receipt is bound to the machine)
- `platform`: `<os>-<arch>` label
- `policy_hashes`: SHA-256 of the integrity script, common.sh, ubuntu/install.sh,
  the contract JSON, and every `templates/desktop/*.desktop` — so changing any
  policy source invalidates the receipt
- `runtime_hosts`: installed versions of node/uv/bun/go/gopls/rustc/dart
- `pinned_source_tools`: installed versions of gitleaks/osv-scanner/etc.
- `user_tools`: installed versions of herdr (and future user tools)
- `desktop_entries`: presence + SHA-256 of `.desktop` files

### Two-layer verify

`verify` performs two independent checks, either failing is `NOT_PROVEN`:

1. **Structural**: re-collect state from the live machine and compare
   dict-equality to the stored receipt. Detects a binary change, a vanished
   file, or a moved path.
2. **Contract**: compare every declared runtime/tool version against
   `rldyour-contract.json`. This is the check `verify.sh` cannot do — it
   compares against bash literals that can drift from the contract.

### Platform awareness

Contract entries may declare an `os` array (e.g. herdr is `"os": ["linux"]`).
`device_integrity.py` filters entries by the current platform, so a Linux-only
tool does not cause `NOT_PROVEN` on macOS where it is never installed.

### Non-fatal in the orchestrator

The parent `bootstrap-device.sh` wires the receipt into phase 0 (preflight,
read-only drift report) and phase 3d (post-apply rebuild + verify). Both calls
swallow failures as warnings, not errors. The receipt is advisory in the
orchestrator: a `NOT_PROVEN` device still reports `bootstrap complete`. This is
deliberate — the receipt is a diagnostic, not a gate. Making it fatal would
block a device from bootstrapping because of drift detected by the very check
that was just introduced.

### Why a separate script, not verify.sh

`verify.sh` is bash and runs per-profile checks. The receipt is Python, crosses
all layers, and compares against the contract JSON (which bash reads only via
inline `python3 - <<'PY'` heredocs). A separate script avoids turning verify.sh
into a polyglot and keeps the receipt's canonical-JSON / atomic-write / SHA-256
primitives in one place.

## Consequences

- A new device that has never been bootstrapped will report `NOT_PROVEN` (no
  receipt). This is expected; the receipt is built during the first apply.
- The receipt is bound to a home directory and a platform label. Copying it
  between machines will fail the structural check.
- Adding a new runtime host or user tool requires adding it to
  `RUNTIME_HOSTS` or the contract's `user_tools`/`desktop_entries` sections.
- The `bootstrap_version` constant must be bumped when the receipt shape
  changes (new keys, changed semantics). It is intentionally separate from the
  adapter contract version.
