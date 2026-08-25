#!/usr/bin/env python3
"""Report where the contract's pins stand against their official sources.

Discovery only. This script never edits a pin, never writes to the contract, and
never downloads an install artifact -- it reads first-party release metadata and
prints what it found. A refresh remains a reviewed change made by a person, with
digests computed from the downloaded artifact.

Why it exists: #66 found seven pins behind their upstreams, one of them a whole
minor version, and nothing in the repository would have said so. Dependabot
covers the GitHub Actions ecosystem; every pin here is a direct upstream
artifact it cannot see.

Fail-closed conditions, each of which exits non-zero:

- a declared source returns no releases at all;
- the newest release is missing an asset the contract depends on;
- an architecture the contract requires is no longer published;
- a probe returns a URL that is not a fixed, versioned location.

A pin that is simply behind its upstream also exits non-zero, unless it carries
an entry in ``INTENTIONAL_HOLDS``. That is the difference between a report and a
check: this used to render `behind` and exit 0, so the scheduled run went green
and the finding existed only inside a job summary nobody opens. #66 found seven
pins behind their upstreams; a mechanism that would have reported them exactly
as quietly is not a fix for that.

A network or rate-limit failure is treated differently, because "GitHub was
rate-limiting us" is not evidence that a pin drifted. One or two `unknown`
results are reported and tolerated. Above ``UNKNOWN_TOLERANCE`` the run has not
learned enough to be evidence of anything and fails as such -- a report that is
mostly "could not tell" should not be indistinguishable from a clean one.

A source that is unreachable *every* week is a different thing from one that
was rate-limited once, and the tolerance alone cannot tell them apart: one
unknown out of twenty-five stays green forever. ``--previous`` closes that.
Given the snapshot from the last run, a pin that was ``unknown`` then and is
``unknown`` now has failed twice in a row for reasons that are no longer
plausibly transient, and it fails the run by name.

That is the whole of the state this script keeps: one previous snapshot, passed
in, never written. It cannot tell you a pin has been unknown for a month -- for
that, read the retained artifacts.

One network snapshot per run. Rendering reads a snapshot rather than probing
again -- the workflow used to call this script twice, once for Markdown and once
for JSON, so the two outputs described two different moments and consumed the
rate limit twice to disagree.

Usage:

    python3 scripts/ci/discover_source_drift.py                    # human-readable
    python3 scripts/ci/discover_source_drift.py --json             # machine-readable
    python3 scripts/ci/discover_source_drift.py --markdown         # job summary
    python3 scripts/ci/discover_source_drift.py --markdown \
        --from-json report.json                                    # render, no network
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "config" / "rldyour-contract.json"

USER_AGENT = "macos-ubuntu-bootstrap-source-drift/1 (+https://github.com/NDDev-OpenNetwork/macos-ubuntu-bootstrap)"
TIMEOUT_SECONDS = 30

# A pin whose current value is intentionally held rather than stale. Each entry
# states why, so a held pin reads as a decision instead of an oversight.
INTENTIONAL_HOLDS: dict[str, str] = {
    "bun": "1.4 is a major runtime transition pending installer and language-server qualification",
    "go": "1.27 is a major toolchain transition pending module and cross-architecture qualification",
    "rust": "1.98 requires a new dated rustup manifest and both architecture hashes",
    "dart": "3.13.2 requires both official SDK archive hashes",
}

# How many sources may be unreachable before the run stops being evidence.
# Two tolerates the transient rate limit this script was already careful about;
# a report where a third of the sources could not be read says nothing about
# whether the pins drifted, and should not be able to say it in green.
UNKNOWN_TOLERANCE = 2


class DiscoveryError(RuntimeError):
    """A source violated the contract's expectations of it."""


@dataclass
class Finding:
    name: str
    pinned: str
    latest: str | None
    status: str                       # current | behind | unknown | violation
    source: str
    detail: str = ""
    assets: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "pinned": self.pinned,
            "latest": self.latest,
            "status": self.status,
            "source": self.source,
            "detail": self.detail,
            "assets": self.assets,
        }


# The only host this script may send a credential to.
GITHUB_API_HOST = "api.github.com"


def _get(url: str) -> Any:
    """Fetch first-party JSON. Network and rate-limit failures raise OSError.

    The token is attached by exact hostname, never by substring. `"api.github.com"
    in url` would also match `https://evil.example.invalid/api.github.com/x`,
    handing the credential to whoever chose that URL. Every URL here is a
    hardcoded constant so it was not reachable, but a token-scoping test that is
    right by accident is one refactor from being wrong.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    token = os.environ.get("GITHUB_TOKEN", "")
    if token and urllib.parse.urlsplit(url).hostname == GITHUB_API_HOST:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _normalize(value: str) -> str:
    """Compare versions without their decorations.

    Upstreams spell the same version at least five ways: `1.2.3`, `v1.2.3`,
    `go1.2.3`, `bun-v1.2.3`, and -- for a monorepo that tags per module --
    `gopls/v1.2.3`. The path segment is dropped first, because stripping a
    leading `go` from `gopls/v0.23.0` yields `pls/v0.23.0`, which this function
    did on its first run.
    """
    value = value.strip().rsplit("/", 1)[-1]
    return re.sub(r"^(bun-v|go|v)", "", value)


def _require_fixed_url(url: str, name: str) -> None:
    """A discovery result naming a moving target is a contract violation.

    `latest`, `stable` and `current` in a download path mean the bytes behind it
    can change without the version changing, which is exactly what this
    repository's pinning exists to prevent.
    """
    for moving in ("/latest/", "/stable/download", "/current/"):
        if moving in url:
            raise DiscoveryError(f"{name}: source returned a mutable URL: {url}")


# --------------------------------------------------------------------------
# Probes. Each returns (latest_version, asset_names) from an official source.
# --------------------------------------------------------------------------


def _github_latest(repo: str, name: str) -> tuple[str, list[str]]:
    data = _get(f"https://api.github.com/repos/{repo}/releases/latest")
    tag = data.get("tag_name")
    if not tag:
        raise DiscoveryError(f"{name}: {repo} published no tag_name")
    assets = [item["name"] for item in data.get("assets", [])]
    for item in data.get("assets", []):
        _require_fixed_url(item.get("browser_download_url", ""), name)
    return tag, assets


def _nodejs_lts(name: str) -> tuple[str, list[str]]:
    releases = _get("https://nodejs.org/dist/index.json")
    lts = [item for item in releases if item.get("lts")]
    if not lts:
        raise DiscoveryError(f"{name}: nodejs.org published no LTS release")
    return lts[0]["version"], lts[0].get("files", [])


def _go_latest(name: str) -> tuple[str, list[str]]:
    releases = _get("https://go.dev/dl/?mode=json")
    if not releases:
        raise DiscoveryError(f"{name}: go.dev published no releases")
    newest = releases[0]
    return newest["version"], [item["filename"] for item in newest.get("files", [])]


def _dart_stable(name: str) -> tuple[str, list[str]]:
    data = _get(
        "https://storage.googleapis.com/dart-archive/channels/stable/release/latest/VERSION"
    )
    version = data.get("version")
    if not version:
        raise DiscoveryError(f"{name}: dart-archive published no version")
    return version, []


def _rust_stable(name: str) -> tuple[str, list[str]]:
    request = urllib.request.Request(
        "https://static.rust-lang.org/dist/channel-rust-stable.toml",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        body = response.read().decode("utf-8")
    match = re.search(r"^\[pkg\.rust\]\nversion = \"([^ \"]+)", body, re.M)
    if not match:
        raise DiscoveryError(f"{name}: rust channel manifest has no pkg.rust version")
    return match.group(1), []


def _npm_latest(package: str, name: str) -> tuple[str, list[str]]:
    data = _get(f"https://registry.npmjs.org/{package}/latest")
    version = data.get("version")
    if not version:
        raise DiscoveryError(f"{name}: npm published no version for {package}")
    return version, []


# --------------------------------------------------------------------------
# The pin inventory: contract location -> official probe.
# --------------------------------------------------------------------------


def _pins(contract: dict[str, Any]) -> list[tuple[str, str, str, Callable[[str], tuple[str, list[str]]], list[str]]]:
    """(name, pinned value, source label, probe, required asset substrings)."""
    runtime = contract["runtime_support"]
    tools = runtime["ubuntu_pinned_source_tools"]
    return [
        ("node", runtime["ubuntu_node_lts"], "nodejs.org/dist/index.json",
         _nodejs_lts, ["linux-x64", "linux-arm64"]),
        ("uv", runtime["ubuntu_uv"], "github:astral-sh/uv",
         lambda n: _github_latest("astral-sh/uv", n),
         ["uv-x86_64-unknown-linux-gnu.tar.gz", "uv-aarch64-unknown-linux-gnu.tar.gz"]),
        ("bun", runtime["ubuntu_bun"], "github:oven-sh/bun",
         lambda n: _github_latest("oven-sh/bun", n),
         ["bun-linux-x64.zip", "bun-linux-aarch64.zip"]),
        ("go", runtime["ubuntu_go"], "go.dev/dl",
         _go_latest, ["linux-amd64.tar.gz", "linux-arm64.tar.gz"]),
        ("rust", runtime["ubuntu_rust"], "static.rust-lang.org stable channel",
         _rust_stable, []),
        ("dart", runtime["ubuntu_dart"], "dart-archive stable",
         _dart_stable, []),
        ("gopls", runtime["ubuntu_gopls"], "github:golang/tools",
         lambda n: _github_latest("golang/tools", n), []),
        ("homebrew-pkg", contract["supply_chain"]["homebrew_pkg_version"],
         "github:Homebrew/brew",
         lambda n: _github_latest("Homebrew/brew", n), ["Homebrew.pkg"]),
        ("herdr", contract["user_tools"]["herdr"]["version"], "github:herdrdev/herdr",
         lambda n: _github_latest("herdrdev/herdr", n),
         ["herdr-linux-x86_64", "herdr-linux-aarch64", "herdr-macos-aarch64"]),
        ("telegram", contract["user_tools"]["telegram"]["version"],
         "github:telegramdesktop/tdesktop",
         lambda n: _github_latest("telegramdesktop/tdesktop", n), []),
        ("codex", contract["harnesses"]["codex"]["version"], "npm:@openai/codex",
         lambda n: _npm_latest("@openai/codex", n), []),
        ("gitleaks", tools["gitleaks"]["version"], "github:gitleaks/gitleaks",
         lambda n: _github_latest("gitleaks/gitleaks", n), []),
        ("osv-scanner", tools["osv-scanner"]["version"], "github:google/osv-scanner",
         lambda n: _github_latest("google/osv-scanner", n), []),
        ("actionlint", tools["actionlint"]["version"], "github:rhysd/actionlint",
         lambda n: _github_latest("rhysd/actionlint", n), []),
        ("hadolint", tools["hadolint"]["version"], "github:hadolint/hadolint",
         lambda n: _github_latest("hadolint/hadolint", n), []),
        ("markdown-oxide", tools["markdown-oxide"]["version"],
         "github:Feel-ix-343/markdown-oxide",
         lambda n: _github_latest("Feel-ix-343/markdown-oxide", n), []),
        ("delta", tools["delta"]["version"], "github:dandavison/delta",
         lambda n: _github_latest("dandavison/delta", n), []),
        ("yq", tools["yq"]["version"], "github:mikefarah/yq",
         lambda n: _github_latest("mikefarah/yq", n), []),
        ("just", tools["just"]["version"], "github:casey/just",
         lambda n: _github_latest("casey/just", n), []),
        ("age", tools["age"]["version"], "github:FiloSottile/age",
         lambda n: _github_latest("FiloSottile/age", n), []),
        ("ast-grep", tools["ast-grep"]["version"], "github:ast-grep/ast-grep",
         lambda n: _github_latest("ast-grep/ast-grep", n), []),
        ("eza", tools["eza"]["version"], "github:eza-community/eza",
         lambda n: _github_latest("eza-community/eza", n), []),
        ("lazygit", tools["lazygit"]["version"], "github:jesseduffield/lazygit",
         lambda n: _github_latest("jesseduffield/lazygit", n), []),
        ("difft", tools["difft"]["version"], "github:Wilfred/difftastic",
         lambda n: _github_latest("Wilfred/difftastic", n), []),
        ("jaq", tools["jaq"]["version"], "github:01mf02/jaq",
         lambda n: _github_latest("01mf02/jaq", n), []),
    ]


def discover(contract: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    for name, pinned, source, probe, required_assets in _pins(contract):
        try:
            latest, assets = probe(name)
        except DiscoveryError as exc:
            findings.append(Finding(name, pinned, None, "violation", source, str(exc)))
            continue
        except (OSError, urllib.error.URLError) as exc:
            # Reachability is not evidence about a pin. Reported, not failed.
            findings.append(Finding(name, pinned, None, "unknown", source,
                                    f"source unreachable: {type(exc).__name__}"))
            continue
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError, IndexError) as exc:
            # The source answered, but not in the shape its contract describes.
            # That is a real finding: an upstream changed its metadata schema and
            # every later reading of it is now guesswork.
            findings.append(Finding(
                name, pinned, None, "violation", source,
                f"source returned unusable metadata: {type(exc).__name__}: {exc}",
            ))
            continue

        missing = [item for item in required_assets
                   if not any(item in candidate for candidate in assets)]
        if missing:
            findings.append(Finding(
                name, pinned, _normalize(latest), "violation", source,
                f"required assets absent from the newest release: {missing}", assets,
            ))
            continue

        status = "current" if _normalize(latest) == _normalize(pinned) else "behind"
        detail = INTENTIONAL_HOLDS.get(name, "") if status == "behind" else ""
        if detail:
            status = "held"
        findings.append(Finding(name, pinned, _normalize(latest), status, source, detail, assets))
    return findings


def render_markdown(findings: list[Finding]) -> str:
    by_status: dict[str, list[Finding]] = {}
    for item in findings:
        by_status.setdefault(item.status, []).append(item)

    lines = ["# Source drift report", ""]
    counts = ", ".join(f"{len(v)} {k}" for k, v in sorted(by_status.items()))
    lines += [f"{len(findings)} pins checked: {counts}.", ""]
    lines += ["| pin | contract | official | status | source |", "|---|---|---|---|---|"]
    for item in sorted(findings, key=lambda f: (f.status != "violation", f.status != "behind", f.name)):
        lines.append(
            f"| `{item.name}` | `{item.pinned}` | `{item.latest or '—'}` | "
            f"{item.status} | {item.source} |"
        )
    detailed = [item for item in findings if item.detail]
    if detailed:
        lines += ["", "## Notes", ""]
        lines += [f"- **{item.name}** — {item.detail}" for item in detailed]
    lines += [
        "",
        "Discovery only: no pin was changed and no install artifact was downloaded.",
        "A refresh is a reviewed change, with every digest computed from the",
        "downloaded artifact rather than copied from a release note.",
    ]
    return "\n".join(lines) + "\n"


def render_text(findings: list[Finding]) -> str:
    width = max(len(item.name) for item in findings)
    lines = []
    for item in sorted(findings, key=lambda f: f.name):
        lines.append(
            f"{item.name:<{width}}  {item.status:<9} pinned={item.pinned:<12} "
            f"latest={item.latest or '-'}"
            + (f"  ({item.detail})" if item.detail else "")
        )
    return "\n".join(lines) + "\n"


def load_snapshot(path: Path) -> list[Finding]:
    """Rebuild findings from a snapshot this script wrote earlier."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        Finding(
            name=item["name"], pinned=item["pinned"], latest=item["latest"],
            status=item["status"], source=item["source"],
            detail=item.get("detail", ""), assets=item.get("assets", []),
        )
        for item in raw
    ]


def report(
    findings: list[Finding],
    *,
    unknown_tolerance: int = UNKNOWN_TOLERANCE,
    previous: list[Finding] | None = None,
) -> int:
    """The exit status the findings justify, and why, on stderr."""
    failed = False

    violations = [item for item in findings if item.status == "violation"]
    for item in violations:
        print(f"source-drift-violation: {item.name}: {item.detail}", file=sys.stderr)
        failed = True

    behind = [item for item in findings if item.status == "behind"]
    for item in behind:
        print(
            f"source-drift-behind: {item.name}: contract pins {item.pinned}, "
            f"{item.source} publishes {item.latest}. Refresh it, or record why "
            "not in INTENTIONAL_HOLDS.",
            file=sys.stderr,
        )
        failed = True

    unknown = [item for item in findings if item.status == "unknown"]
    for item in unknown:
        print(f"source-drift-unknown: {item.name}: {item.detail}", file=sys.stderr)

    # Unknown twice running is not a rate limit any more.
    if previous is not None:
        previously_unknown = {item.name for item in previous if item.status == "unknown"}
        persistent = sorted(item.name for item in unknown if item.name in previously_unknown)
        for name in persistent:
            print(
                f"source-drift-unknown-persists: {name}: unreachable in this run and "
                "in the previous one. One failure is a rate limit; two in a row is a "
                "source this repository can no longer check.",
                file=sys.stderr,
            )
            failed = True

    if len(unknown) > unknown_tolerance:
        print(
            f"source-drift-unknown: {len(unknown)} of {len(findings)} sources could "
            f"not be read, above the tolerance of {unknown_tolerance}. This run is "
            "not evidence that the pins are current.",
            file=sys.stderr,
        )
        failed = True

    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--markdown", action="store_true", help="job-summary output")
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument(
        "--from-json", type=Path, default=None,
        help="render a snapshot this script wrote earlier instead of probing again",
    )
    parser.add_argument(
        "--unknown-tolerance", type=int, default=UNKNOWN_TOLERANCE,
        help="how many unreachable sources a run may report and still be evidence",
    )
    parser.add_argument(
        "--previous", type=Path, default=None,
        help="the previous run's snapshot; a source unknown in both fails this run",
    )
    args = parser.parse_args(argv)

    if args.from_json is not None:
        findings = load_snapshot(args.from_json)
    else:
        contract = json.loads(args.contract.read_text(encoding="utf-8"))
        findings = discover(contract)

    if args.json:
        print(json.dumps([item.as_dict() for item in findings], indent=2, sort_keys=True))
    elif args.markdown:
        print(render_markdown(findings), end="")
    else:
        print(render_text(findings), end="")

    previous = None
    if args.previous is not None and args.previous.is_file():
        try:
            previous = load_snapshot(args.previous)
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            # An unreadable previous snapshot is not evidence about a pin, and
            # refusing to run because last week's artifact expired would make
            # this check fail for a reason that has nothing to do with drift.
            print(f"source-drift: previous snapshot unusable ({exc}); "
                  "persistence check skipped", file=sys.stderr)
    return report(
        findings, unknown_tolerance=args.unknown_tolerance, previous=previous,
    )


if __name__ == "__main__":
    raise SystemExit(main())
