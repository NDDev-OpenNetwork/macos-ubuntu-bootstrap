# Branch rulesets

`branch-main.json` is a **mirror** of the live ruleset protecting `main`. It is
documentation and a test fixture, not something any workflow applies: GitHub is
the authority, and changing the live ruleset requires repository-administration
rights that CI does not have and should not have.

**A mirror may not declare a check the live ruleset does not enforce.**
`scripts/ci/check_required_contexts.py` fails when it does, and CI runs it
against the live rules API on every pull request, so the two cannot drift in
either direction. Intent to require a *new* check belongs in an issue and in the
change that makes the check able to report — not in this file. Declaring it here
first is not a proposal anyone acts on; it is a false statement about what
protects the branch, and every agent that reads the repository believes it.

That is not hypothetical. This file previously carried an eighth context,
`evidence-gate`, together with a ready-to-paste command to apply it and this
justification:

> `evidence-gate` runs on `pull_request` and on pushes to `main`.

It does not. `platform-evidence.yml` has had `pull_request` as its **only**
trigger since #77 closed #75 — a `push: main` trigger would hand a contributor's
unreviewed head code the default-branch cache scope. So:

- a pull request that touches none of the workflow's `paths:` never gets the
  context at all, and a required context that never reports leaves the pull
  request permanently pending;
- a fork's pull request skips every producer job
  (`if: …head.repo.full_name == github.repository`), and `evidence-gate` turns a
  `skipped` need into `exit 1`, so it is not merely absent but red.

Applying that command would therefore have made every fork pull request
unmergeable and every out-of-scope pull request unmergeable, for a control that
was never able to report on either.

## Three lists, one answer

The contexts `main` enforces are stated in three places, and all three must
agree:

| Where | What it is |
| --- | --- |
| the live ruleset (`GET /repos/{owner}/{repo}/rules/branches/main`) | the authority |
| `.github/rulesets/branch-main.json` | this mirror, reviewed in a diff |
| `.gds/repository.yaml` → `verification.required_contexts` | what the control plane reads |

`scripts/ci/check_required_contexts.py` compares the two checked-in lists on
every test run, and all three when it can reach the API. Before this, the
`.gds` list was bound by nothing at all: it was accurate, and nothing would have
noticed if it stopped being.

## Adding a required check

1. Make the check able to report a definite result for **every** pull request
   that can reach `main` — in-repository, fork, and out-of-path.
2. Land that, and let it run green on real pull requests.
3. Then, in one act: add it to the live ruleset and to this mirror and to
   `.gds/repository.yaml`.

```bash
# 1. read the live ruleset and confirm the mirror still matches it everywhere else
gh api /repos/NDDev-it-com/macos-ubuntu-bootstrap/rules/branches/main \
  --jq '[.[] | select(.type=="required_status_checks")
         | .parameters.required_status_checks[].context] | sort'

# 2. apply the mirror
gh api --method PUT /repos/NDDev-it-com/macos-ubuntu-bootstrap/rulesets/20188391 \
  --input .github/rulesets/branch-main.json

# 3. prove all three agree
python3 scripts/ci/check_required_contexts.py --live
```

Step 3 is the point. A ruleset change that is not followed by a green
`--live` run has not been finished.

## Pending

`evidence-gate` is the one check worth requiring that cannot report yet. It
becomes eligible once fork pull requests and out-of-path pull requests each
receive a documented, definite result. Until then it is deliberately absent from
all three lists.
