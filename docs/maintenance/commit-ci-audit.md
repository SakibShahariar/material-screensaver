# Commit CI Audit Ledger

Persistent repository-specific record of commit-level CI checks and red-cross investigations.

## How to use this ledger

1. Read this file before auditing commit checks.
2. Check only commits newer than the checkpoint, plus older **red**, **pending**, or explicitly unresolved entries.
3. Record exact commit SHAs and observed results; never infer from missing badges or empty API responses.
4. Preserve failures and append diagnosis, fix, rerun, and final-outcome evidence.
5. Advance the checkpoint only after reviewing the range; carry unresolved entries forward.

## Result meanings

| Result | Meaning |
|---|---|
| **green** | Completed successful check/run directly observed. |
| **red** | Completed failing check/run directly observed. |
| **pending** | Check/run exists but is unfinished. |
| **unavailable** | Available evidence did not expose a result; not a pass or failure. |
| **not applicable** | Workflow configuration confirms no relevant check is triggered. |

## Checkpoint

- Repository: `SakibShahariar/material-screensaver`
- Default branch: `master`
- Checkpoint SHA: `44ec3498851aff1735124f2d80ef232f35af6c84`
- Initialized: 2026-11-02
- Baseline correction: a workflow run for the checkpoint commit was later found and inspected; it failed in the test-suite step. The failure is recorded below rather than treating the earlier empty combined-status response as authoritative.
- Next session: review commits after this checkpoint, including the ledger and `AGENTS.md` setup commits; investigate any older red/pending commit specifically identified by the owner.

## Initial baseline

| Commit SHA | Subject | CI result | Checked | Follow-up |
|---|---|---|---|---|
| `44ec3498851aff1735124f2d80ef232f35af6c84` | docs: improve maintenance workflow guidance | red | 2026-11-02 | [Run 41401009285](https://github.com/SakibShahariar/material-screensaver/actions/runs/41401009285): tests failed; lint passed. |

## Red-cross investigation log

The following commits all have an observed failed test job and successful lint job. The same two assertions failed in `tests/test_lock_logic.py`: `test_lock_when_inactive_is_noop` (unexpected hide count 1) and `test_repeat_active_changed_only_hides_once` (unexpected hide count 2). The test fixture leaked the daemon's `_is_showing` state between cases; the production hide path clears that flag, but the fake hide callback did not. The spawn-race test added in `930e51d` sets `_is_showing=True` without restoring it. Classification: test-fixture regression, not evidence of a production lock-handling regression.

| Commit SHA | Subject | CI result | Workflow run | Failed job / step |
|---|---|---|---|---|
| `b7856e4c6b5f29bf5fe94c8288c817416ba3e200` | docs: add persistent commit CI audit ledger | red | [41456575938](https://github.com/SakibShahariar/material-screensaver/actions/runs/41456575938) | tests / Run test suite |
| `6495447b0262de2312dfbc6cfab77db49a2eff88` | docs: document incremental commit CI auditing | red | [41456581218](https://github.com/SakibShahariar/material-screensaver/actions/runs/41456581218) | tests / Run test suite |
| `ffb4e1bd8cb11bba701086956712ab0f104a9b47` | docs: define issue triage categories | red | [41573380962](https://github.com/SakibShahariar/material-screensaver/actions/runs/41573380962) | tests / Run test suite |
| `aaff2f7ec7fd9110075b4dcc6a301e25246b1083` | docs(agents): define administrative commit hygiene | red | [41597938193](https://github.com/SakibShahariar/material-screensaver/actions/runs/41597938193) | tests / Run test suite |

Fix commit and rerun outcome will be appended after verification.

### Failure record template

- Commit SHA:
- Commit subject:
- First observed (date):
- Workflow / run URL:
- Failed job / step:
- Failure summary:
- Classification: regression / pre-existing / inconclusive
- Fix commit(s):
- Rerun attempt(s) and result:
- Final verified outcome:
- Remaining follow-up:

## Session history

| Date | Reviewed range / checkpoint | Result summary |
|---|---|---|
| 2026-11-02 | Initial checkpoint: `44ec3498851aff1735124f2d80ef232f35af6c84` | Latest commit queried; empty status response recorded as unavailable. Earlier history not retroactively audited. |
