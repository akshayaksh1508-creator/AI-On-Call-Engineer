# Day 4: Fix Generation and Sandbox Verification

## Result

The Day 4 exit gate passed on the five simplest code faults: **5/5 patches were sandbox verified (100%)**, above the required 3/5.

Each run used a disposable Git worktree. The fault reproduction failed on the injected buggy fixture, then the focused unit test and the same reproduction passed after applying the patch. Worktrees were removed after each run.

| Fault | Service | Baseline reproduction failed | Unit test passed | Fixed reproduction passed |
| --- | --- | --- | --- | --- |
| `fault_001_bad_deploy` | orders | Yes | Yes | Yes |
| `fault_002_off_by_one` | orders | Yes | Yes | Yes |
| `fault_003_wrong_status_code` | payments | Yes | Yes | Yes |
| `fault_004_bad_parsing` | gateway | Yes | Yes | Yes |
| `fault_005_unhandled_exception` | orders | Yes | Yes | Yes |

## Implemented

- Fix proposals validate cited evidence, patch applicability, target paths, and patch size. Selection covers rollback, config change, and patch.
- Regression test code is syntax and assertion checked, with a runner that proves fail-before/pass-after.
- `POST /verify/sandbox` applies a candidate patch in an isolated Git worktree and returns a partial `VerificationResult` for tests and reproduction.
- The GitHub PR client formats cause, evidence IDs, expected metric effect, and test results; retries update an existing open PR instead of creating duplicates.

## Limits of this run

- Candidate diffs were derived from the repository's known `buggy_app.py` and `patched_app.py` fixture pairs. This measures the patch validation and verification path; it does not measure an LLM's ability to invent a fix.
- Tests ran on the host because Docker is not installed in this environment.
- PR descriptions and idempotency were verified in mock mode. The checkout has no `.env`, `GITHUB_TOKEN`, or `GITHUB_SANDBOX_REPO`, so no live sandbox PR was created.
- The verifier intentionally leaves canary and production metric recovery for Day 5.

The per-fault machine-readable results are in [`results/day4_execution.json`](../results/day4_execution.json). Re-run with `python scripts/run_day4.py`.

Focused implementation suite: **17 passed, 2 skipped**. The skips occur when tests are run
against the clean baseline, where the pagination and promotional discount fault helpers do not
exist; the harness overlays those fault fixtures and verifies both cases successfully.
