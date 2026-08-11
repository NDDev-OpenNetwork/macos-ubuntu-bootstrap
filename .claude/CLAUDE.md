@AGENTS.md

# Claude Code delta

`AGENTS.md` above is this module's guide and is imported, not restated. This
file carries only what differs for Claude Code.

This file used to be a second copy of the project contract. It drifted: it did
not know the `desktop-builds` profile two releases after that profile shipped,
it named the server execution policy with a retired token in one paragraph and
the current one in another, and it still instructed the codex `safe` setup
months after that gate was removed. Keep it a delta. `tests/
test_agent_context.py` fails if it grows back into a specification or starts
copying pins.

## Where facts live

- Machine-readable pins, profiles and ownership: `config/rldyour-contract.json`.
  Never restate a version here; the contract is the only place it is correct.
- Behaviour: the scripts. Rationale for a boundary: `docs/adr/`.
- Whether a rule holds on a device: run the verifier, do not read prose.

## Working in this repository

- A task contained in this module goes straight to the relevant source and its
  verification command. `gds-orient` is for estate, device, topology and
  cross-repository scope.
- Serena memories under `.serena/memories/` are derived evidence and are
  deliberately few. They point at sources; they do not carry pins or policy.
- Prefer the repository's own commands over ad-hoc equivalents, so a failure is
  reproducible from the guide alone.
- Plan mode is the default everywhere. Claiming runtime evidence that was not
  produced is the one unrecoverable mistake in this repository — a plan-mode run
  proves nothing about apply, and neither macOS nor server behaviour can be
  demonstrated from an Ubuntu desktop.
