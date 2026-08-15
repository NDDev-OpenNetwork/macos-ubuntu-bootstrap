"""Discovery must report drift without ever becoming a way to change a pin.

`scripts/ci/discover_source_drift.py` reads first-party release metadata and
says where the contract stands. It is deliberately incapable of editing the
contract, and its failure modes are chosen so the report stays trustworthy: a
source that contradicts the contract fails the run, while a source that is
merely unreachable does not, because "GitHub rate-limited us" is not evidence
that a pin drifted and a report that cries wolf gets ignored.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/ci/discover_source_drift.py"
SPEC = importlib.util.spec_from_file_location("discover_source_drift", MODULE_PATH)
assert SPEC and SPEC.loader
drift = importlib.util.module_from_spec(SPEC)
# Registered before exec: `@dataclass` resolves its own module through
# `sys.modules[cls.__module__]`, which is absent for a module loaded by path.
sys.modules["discover_source_drift"] = drift
SPEC.loader.exec_module(drift)

CONTRACT = json.loads((ROOT / "config/rldyour-contract.json").read_text(encoding="utf-8"))


def _contract_with(**overrides) -> dict:
    data = json.loads(json.dumps(CONTRACT))
    for dotted, value in overrides.items():
        node = data
        *path, leaf = dotted.split(".")
        for key in path:
            node = node[key]
        node[leaf] = value
    return data


# ----------------------------- normalisation -----------------------------


@pytest.mark.parametrize("raw,expected", [
    ("1.2.3", "1.2.3"),
    ("v1.2.3", "1.2.3"),
    ("go1.26.6", "1.26.6"),
    ("bun-v1.3.14", "1.3.14"),
    # A monorepo tagging per module. Stripping a leading `go` from this yields
    # `pls/v0.23.0`, which the first version of this function actually produced
    # and reported as drift against an identical pin.
    ("gopls/v0.23.0", "0.23.0"),
])
def test_every_upstream_tag_spelling_normalizes(raw: str, expected: str) -> None:
    assert drift._normalize(raw) == expected


# ----------------------------- fail-closed -----------------------------


def test_a_missing_required_asset_is_a_violation(monkeypatch) -> None:
    """A release that no longer publishes an architecture we install is drift."""
    monkeypatch.setattr(drift, "_get", lambda url: {
        "tag_name": "v9.9.9",
        "assets": [{"name": "uv-x86_64-unknown-linux-gnu.tar.gz",
                    "browser_download_url": "https://example.invalid/v9.9.9/x86_64"}],
    })
    findings = {item.name: item for item in drift.discover(CONTRACT)}
    uv = findings["uv"]
    assert uv.status == "violation"
    assert "aarch64" in uv.detail


def test_a_mutable_download_url_is_a_violation(monkeypatch) -> None:
    """A moving target defeats the point of pinning."""
    monkeypatch.setattr(drift, "_get", lambda url: {
        "tag_name": "v9.9.9",
        "assets": [{"name": "herdr-linux-x86_64",
                    "browser_download_url": "https://example.invalid/latest/herdr"}],
    })
    findings = {item.name: item for item in drift.discover(CONTRACT)}
    assert findings["herdr"].status == "violation"
    assert "mutable URL" in findings["herdr"].detail


def test_a_source_publishing_nothing_is_a_violation(monkeypatch) -> None:
    monkeypatch.setattr(drift, "_get", lambda url: [] if "nodejs" in url else {"tag_name": None})
    findings = {item.name: item for item in drift.discover(CONTRACT)}
    assert findings["node"].status == "violation"
    assert findings["uv"].status == "violation"


def test_violations_fail_the_run(monkeypatch, capsys) -> None:
    monkeypatch.setattr(drift, "_get", lambda url: {"tag_name": None})
    assert drift.main(["--json"]) == 1
    assert "source-drift-violation" in capsys.readouterr().err


# --------------------- reachability is not drift ---------------------


@pytest.mark.parametrize("failure", [
    urllib.error.URLError("dns"),
    urllib.error.HTTPError("u", 403, "rate limited", {}, None),
    OSError("connection reset"),
    TimeoutError("timed out"),
])
def test_an_unreachable_source_is_reported_as_unknown(monkeypatch, failure) -> None:
    """Reachability is not evidence about a pin, whatever the transport said."""
    def explode(url):
        raise failure
    monkeypatch.setattr(drift, "_get", explode)
    monkeypatch.setattr(drift, "_rust_stable", lambda name: (_ for _ in ()).throw(failure))

    findings = drift.discover(CONTRACT)
    assert findings, "discovery produced nothing"
    assert all(item.status == "unknown" for item in findings), (
        [f"{i.name}={i.status}" for i in findings if i.status != "unknown"]
    )


def _finding(name: str, status: str, **kw) -> object:
    return drift.Finding(
        name=name, pinned=kw.get("pinned", "1.0.0"), latest=kw.get("latest"),
        status=status, source=kw.get("source", "example"), detail=kw.get("detail", ""),
    )


def test_a_few_unreachable_sources_are_tolerated(capsys) -> None:
    """A rate limit on two of twenty-five must not read as drift."""
    findings = [_finding(f"tool{i}", "current") for i in range(20)]
    findings += [_finding("a", "unknown"), _finding("b", "unknown")]
    assert drift.report(findings) == 0
    assert "source-drift-unknown: a" in capsys.readouterr().err


def test_mostly_unknown_is_not_a_clean_report(capsys) -> None:
    """The silent-green case: nothing was read, and it looked like health."""
    findings = [_finding(f"tool{i}", "unknown") for i in range(10)]
    assert drift.report(findings) == 1
    assert "not evidence that the pins are current" in capsys.readouterr().err


def test_the_unknown_tolerance_is_the_boundary() -> None:
    ok = [_finding("x", "current")] + [_finding(f"u{i}", "unknown") for i in range(2)]
    over = [_finding("x", "current")] + [_finding(f"u{i}", "unknown") for i in range(3)]
    assert drift.report(ok, unknown_tolerance=2) == 0
    assert drift.report(over, unknown_tolerance=2) == 1


# ----------------------------- drift itself -----------------------------


def test_a_newer_upstream_is_reported_as_behind(monkeypatch) -> None:
    monkeypatch.setattr(drift, "_npm_latest", lambda pkg, name: ("999.0.0", []))
    findings = {item.name: item for item in drift.discover(CONTRACT)}
    assert findings["codex"].status == "behind"
    assert findings["codex"].latest == "999.0.0"


def test_a_behind_pin_fails_the_run(capsys) -> None:
    """Rendering a finding and exiting zero is how #66 could have recurred."""
    findings = [_finding("x", "current"), _finding("codex", "behind", latest="999.0.0")]
    assert drift.report(findings) == 1
    err = capsys.readouterr().err
    assert "source-drift-behind: codex" in err
    assert "INTENTIONAL_HOLDS" in err, "the message must say what to do about it"


def test_a_held_pin_does_not_fail_the_run(capsys) -> None:
    """A hold is a decision that was made, not a finding waiting to be made."""
    findings = [_finding("x", "current"),
                _finding("codex", "held", latest="999.0.0", detail="pending advisory")]
    assert drift.report(findings) == 0
    assert capsys.readouterr().err == ""


def test_rendering_reads_a_snapshot_instead_of_probing_again(tmp_path, monkeypatch) -> None:
    """One run, one moment.

    The workflow used to invoke this script twice -- once for Markdown, once for
    JSON -- so the summary and the artifact were two network snapshots taken
    minutes apart, free to disagree, each spending the rate limit the other
    needed.
    """
    calls = []
    monkeypatch.setattr(drift, "_get", lambda url: calls.append(url) or {"tag_name": "v1"})

    snapshot = tmp_path / "report.json"
    snapshot.write_text(json.dumps([
        _finding("codex", "behind", latest="999.0.0").as_dict(),
        _finding("x", "current").as_dict(),
    ]), encoding="utf-8")

    assert drift.main(["--markdown", "--from-json", str(snapshot)]) == 1
    assert calls == [], "rendering a snapshot must not touch the network"

    restored = drift.load_snapshot(snapshot)
    assert [item.status for item in restored] == ["behind", "current"]


def test_an_intentional_hold_reads_as_a_decision(monkeypatch) -> None:
    """A held pin must not look like an oversight."""
    monkeypatch.setattr(drift, "_npm_latest", lambda pkg, name: ("999.0.0", []))
    monkeypatch.setitem(drift.INTENTIONAL_HOLDS, "codex", "held pending vendor advisory")
    findings = {item.name: item for item in drift.discover(CONTRACT)}
    assert findings["codex"].status == "held"
    assert findings["codex"].detail == "held pending vendor advisory"


# ------------------------- coverage of the contract -------------------------


def test_every_pinned_source_tool_has_a_probe() -> None:
    """A tool added to the contract without a probe would drift unseen."""
    probed = {name for name, *_ in drift._pins(CONTRACT)}
    declared = set(CONTRACT["runtime_support"]["ubuntu_pinned_source_tools"])
    assert declared <= probed, f"pinned tools with no discovery probe: {sorted(declared - probed)}"


def test_every_runtime_host_and_user_tool_has_a_probe() -> None:
    probed = {name for name, *_ in drift._pins(CONTRACT)}
    for expected in ("node", "uv", "bun", "go", "rust", "dart", "gopls",
                     "herdr", "telegram", "codex", "homebrew-pkg"):
        assert expected in probed, f"{expected} has no discovery probe"


def test_discovery_cannot_write_the_contract() -> None:
    """The one property that keeps this safe to run on a schedule."""
    import re as _re

    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in ("write_text", "write_bytes", "urlretrieve", "subprocess", "os.remove"):
        assert forbidden not in source, (
            f"discovery gained {forbidden!r}; it must only read metadata"
        )
    # `open(` alone matches `urlopen(`, which is how this script reads. Look for
    # a write mode instead.
    assert not _re.search(r"\bopen\([^)]*['\"][wax]", source), (
        "discovery opened a file for writing; it must only read metadata"
    )


@pytest.mark.parametrize("url,expected", [
    ("https://api.github.com/repos/x/y/releases/latest", True),
    # A lookalike host that merely contains the API host as a substring.
    ("https://evil.example.invalid/api.github.com/repos/x/y", False),
    ("https://api.github.com.evil.example.invalid/repos/x/y", False),
    ("https://nodejs.org/dist/index.json", False),
    ("https://registry.npmjs.org/@openai/codex/latest", False),
])
def test_the_token_goes_only_to_the_github_api_host(monkeypatch, url, expected) -> None:
    """`"api.github.com" in url` would hand the credential to a lookalike host.

    Every URL in this script is a hardcoded constant, so it was not reachable --
    but a credential boundary that is right by accident is one refactor away
    from being wrong, and CodeQL was correct to say so.
    """
    seen: dict[str, str] = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"{}"

    def capture(request, timeout=None):
        seen.update(request.headers)
        return _Response()

    monkeypatch.setenv("GITHUB_TOKEN", "secret-value")
    monkeypatch.setattr(drift.urllib.request, "urlopen", capture)
    drift._get(url)
    carried = any("secret-value" in value for value in seen.values())
    assert carried is expected, f"{url}: token carried={carried}, expected {expected}"


# ----------------- unknown twice running is not a rate limit -----------------


def test_one_unknown_run_is_still_tolerated(capsys) -> None:
    """The transient case the tolerance exists for must stay green."""
    previous = [_finding("a", "current"), _finding("b", "current")]
    now = [_finding("a", "unknown"), _finding("b", "current")]
    assert drift.report(now, previous=previous) == 0
    assert "source-drift-unknown-persists" not in capsys.readouterr().err


def test_unknown_in_two_consecutive_runs_fails(capsys) -> None:
    """One unknown out of twenty-five stays inside the tolerance forever.

    That is the residual the tolerance alone cannot close: a source that is
    unreachable every single week looks exactly like one that was rate-limited
    once. Two runs is enough to tell them apart.
    """
    previous = [_finding("a", "unknown"), _finding("b", "current")]
    now = [_finding("a", "unknown"), _finding("b", "current")]
    assert drift.report(now, previous=previous) == 1
    err = capsys.readouterr().err
    assert "source-drift-unknown-persists: a" in err
    assert "no longer plausibly transient" in err or "can no longer check" in err


def test_a_recovered_source_does_not_fail(capsys) -> None:
    """Unknown last week, readable now, is the system working."""
    previous = [_finding("a", "unknown")]
    now = [_finding("a", "current")]
    assert drift.report(now, previous=previous) == 0
    assert capsys.readouterr().err == ""


def test_a_newly_unknown_source_does_not_fail_on_its_first_run() -> None:
    previous = [_finding("a", "current"), _finding("b", "current")]
    now = [_finding("a", "current"), _finding("b", "unknown")]
    assert drift.report(now, previous=previous) == 0


def test_without_a_previous_snapshot_nothing_escalates() -> None:
    """A first run, or an expired artifact, must not invent a persistent failure."""
    now = [_finding("a", "unknown"), _finding("b", "current")]
    assert drift.report(now, previous=None) == 0


def test_an_unusable_previous_snapshot_skips_the_check(tmp_path, capsys) -> None:
    """Retention is not evidence about a pin.

    Refusing to check for drift because last week's artifact aged out, or came
    back as HTML from a redirect, would be a failure about storage rather than
    about the thing being watched.
    """
    broken = tmp_path / "previous.json"
    broken.write_text("<!DOCTYPE html>not json", encoding="utf-8")
    assert drift.main(["--json", "--previous", str(broken)]) in (0, 1)
    assert "previous snapshot unusable" in capsys.readouterr().err
