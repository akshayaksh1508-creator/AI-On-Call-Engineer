# /fixer

- **Owner:** Person B
- **Role:** Fix generation engine producing minimal diffs, rollbacks, config updates, and regression tests.

*Refer to Architecture Section 5 for directory ownership and collaboration rules.*

## Day 4 interfaces

`Fixer(repo_root).proposal(...)` selects rollback for a recent deployment only when a clean
revert is available, selects config remediation for config faults, and otherwise validates a
patch before returning a `FixProposal`. Patch validation checks cited evidence IDs, allows only
`target-app/` paths by default, limits the number of touched files, and runs `git apply --check`.

`write_regression_test(...)` accepts a generated unittest or pytest test only when its Python syntax is valid
and it contains an assertion. `verify_fail_then_pass(...)` copies that test into separate buggy
and fixed checkouts and runs the same test command against each; callers should pass isolated
worktrees and a bounded command.
