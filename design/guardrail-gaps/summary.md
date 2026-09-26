# PR summary: guardrail gaps

## Summary

This PR fixes the findings that the review of PR #2 left open at its
three-round cap.

- **A test rebound to a lambda no longer passes.** A module-level
  `globals()["test_x"] = lambda: None` used to replace a real test, and the
  gate said PASS on a branch that breaks "never below neutral". Now the root
  `conftest.py` records each test's code location in the JUnit results, and
  the `evidence` check requires every passed result to come from the `def` in
  the source. Guardrails also flag module-level assignments that could
  rebind a test.
- **Asserts hidden in dead code are flagged.** Any change to the body of an
  existing test or helper, compared as an AST, is NEEDS_HUMAN. That covers
  `if False:`, `try/except AssertionError` and an unused nested `def`.
- **Skips no longer always FAIL.** A skip that is already in the merge-base is
  accepted, and a new one is NEEDS_HUMAN.
- **The push guard's holes are closed:** combined flags like `-uf`,
  `/usr/bin/git`, `command`/`env`/`sudo` wrappers, and `bash -c`. Its false
  positives on `-o <value>` and shell redirects (`2>&1`) are fixed.

The drill now has 21 rows, including the two new attacks, and all 21 behave as
expected.

## Why

These are the holes the adversarial reviewer showed in `master`'s judge:
- ways to get PASS, or to hide a weakened test, using only edits that weren't
  flagged;
- a skip rule that would have broken every later PR once a skip was accepted.

## Not done

- **This PR is NEEDS_HUMAN by design.** It edits `tools/verify_lib/` and
  `tools/hooks/`, which are guardrail files. `master`'s own judge ran on it,
  and every check passed, including a second test run with `master`'s
  guardrail files put back. Merge it through the PR bypass after reviewing the
  diff.
- **Mutation testing** and the **skill updates** are still follow-ups.
