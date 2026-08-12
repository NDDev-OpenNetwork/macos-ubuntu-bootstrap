# macOS and Ubuntu bootstrap contributor instructions

This repository owns plan-first installation and verification for Apple Silicon
macOS, Ubuntu 24.04/26.04 desktops, and Ubuntu 24.04/26.04 servers.

The sources of truth are `scripts/bootstrap.sh`, `scripts/lib/common.sh`, the
platform installers/verifiers, `config/rldyour-contract.json`, `README.md`, and
`SECURITY.md`. Keep implementation, verification, contract, tests, docs,
`VERSION`, and `CHANGELOG.md` synchronized.

## Contract 3.0.0

- macOS supports `desktop`, with optional GUI, no Docker, and source-analysis
  plus local-check tooling.
- Ubuntu requires explicit `desktop`, `desktop-builds`, or `server` selection.
- Ubuntu `desktop` has no Docker; `desktop-builds` adds rootful Docker for local
  builds/tests without the server baseline.
- Ubuntu `server` is headless, defaults to rootful Docker, and supports explicit
  `rootless` or `none` alternatives.
- All profiles receive Codex CLI, Claude Code, Grok Build, zsh configuration,
  modern terminal tools, source-quality tools, and applicable language servers.
- `cx`, `cl`, and `gk` invoke the three AI CLIs in their documented unrestricted
  modes. Keep the ordinary vendor commands unchanged.
- Google Chrome stable is the only installed browser. macOS GUI installs
  ChatGPT, Claude, Ghostty, cmux, RustDesk, and Telegram. Ubuntu GUI installs
  Chrome, RustDesk, Telegram, and removes Firefox.
- Herdr is installed on macOS and Ubuntu desktop profiles, including headless
  desktop mode where the upstream binary supports it.

## Implementation rules

- Keep entrypoints strict, idempotent, plan-aware, and non-interactive.
- Never pipe a network response into a shell. Download, verify reviewed integrity
  metadata, then execute.
- Use atomic managed-file updates. Preserve unmanaged/user-modified files.
- Never read, print, store, upload, or synthesize authentication credentials.
- Keep desktop source/check manifests free of deployment orchestration. Keep
  server runtime and hardening in `scripts/ubuntu/server.sh`.
- Preserve exact runtime receipts and architecture hashes for fixed artifacts.
- Do not add mutable dependency resolution where a frozen/pinned path exists.

## Ubuntu server safeguards

The full compositor runs as the non-root sudo-capable owner. Never grant Docker
group membership automatically. UFW, key-only SSH, and Fail2ban are independent
opt-ins. Validate SSH syntax and live contexts before reload, preserve the active
service/socket provider, add the SSH allow rule before enabling UFW, validate
Fail2ban before restart, and roll back failed managed changes. Do not upgrade
existing packages or healthy Docker implicitly.

## Verification

```bash
bash scripts/ci/lint.sh
bash scripts/ci/validate.sh
python3 -m pytest
```

Use the strict platform verifiers on real target machines when platform behavior
changes. Do not claim runtime evidence that was not produced.

Preserve unrelated worktree changes. Use atomic Conventional Commits when
committing. This public repository executes untrusted fork PR code; reusable
workflow callers with a `runner` input must explicitly pass `ubuntu-latest`.
