# Branch rulesets

`branch-main.json` records the repository-owned desired policy and mirrors the
live `main` ruleset after its journaled application. Ordinary CI is advisory:
failures remain visible and produce repository-local evidence issues, while
merge and deployment do not wait for the broad matrix. Pull requests, signed
commits, deletion protection and non-fast-forward protection remain required.

`scripts/ci/check_required_contexts.py --live` compares the ordinary required
contexts with the live branch rules API. An explicit empty list is valid;
malformed JSON, malformed rules, duplicates and API errors fail. A successful
local-only check proves the source declaration; only the authenticated live
comparison proves convergence with GitHub.

The `.gds/repository.yaml` anchor selects the same continuous-development policy
and keeps local verification commands. The source ruleset does not apply itself:
provider changes use the estate's exact plan, apply and verification transaction.
Record the operation and readback before reporting the source and live policy as
synchronized. CI needs only read access for the comparison.

Release publication has separate requirements. `release.yml` requires
`bootstrap-gate` on the candidate, verifies that its tree equals the PR head
whose platform evidence was produced, and opens the verdict artifact to prove
that required evidence exists. A green but out-of-scope or skipped evidence gate
cannot authorize publication. These checks remain enforced independently of the
ordinary merge ruleset. A changed merge tree must obtain matching evidence.

```bash
python3 scripts/ci/check_required_contexts.py
python3 scripts/ci/check_required_contexts.py --live
```
