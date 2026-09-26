# PR summary: agent guardrails

## Summary

This PR makes the repository, not the agent, decide whether a change is good.
`tools/verify` is the one judge. It runs every check and returns `PASS`, `FAIL`,
`NEEDS_HUMAN` or `ERROR` as its exit code, and it writes a report pinned to the
commit.

What it checks:
- **lint and types**: ruff and mypy, as Bazel tests;
- **AGENTS.md conventions**: no comments or docstrings, module docstrings that
  point at real docs pages, a `py_test` rule and the pytest footer for every
  test file, and Markdown links and anchors that resolve;
- **the service contract**: a proto listing that may only grow;
- **tiered tests**: fast, slow and timing tiers, with no retries;
- **branch checks**: commit messages, docs updated in the same commit as the
  behavior change, and tests weakened on the branch;
- **coverage**: every tracked file is seen by some check.

How the verdict is kept honest:
- The gate builds and tests a clean checkout of HEAD, never the working tree.
- The copy of the judge it runs comes from the merge-base.
- When the branch changes a guardrail, the tests run a second time with the
  base's guardrail files put back.

Around the judge:
- Claude Code hooks give per-edit and on-stop feedback.
- Git hooks, `tools/pr_body` and `tools/agent/start_build.sh` connect it to the
  idea → PR workflow.
- A GitHub workflow runs the base's judge on every PR.
- A drill plants 16 known faults and confirms each verdict.

## Why

The AGENTS.md rules held only as long as an agent read and followed them.
Commits in this very branch show why that isn't enough:
- A reviewer found that new Bazel packages were invisible to every check.
- A formatting slip passed local runs because they tested the working copy
  instead of the commit.
- The judge's own first run found four bugs in the judge.

Each of these is now caught by a script, not by care.

## Not done

- **Review stopped at its cap with findings open.** The third review round
  found one blocker and two majors that are not fixed. The blocker: a
  module-level `globals()["test_x"] = lambda: None` replaces a real test,
  evidence sees a passed `test_x`, and the gate says PASS on a branch that
  breaks "never below neutral". The majors: asserts hidden in dead code
  aren't flagged, and skips are always FAIL. See the last table in
  `design/agent-guardrails/review-log.md` for the proposed fixes.

- **Mutation testing** (plan step 9) is not implemented. `--deep` runs flake
  re-runs only.
- **Dogfood run** (plan step 17) isn't done: a full design → build → PR run
  needs this branch merged and the skills updated.
- **The skills** (`/algo-design-loop`, `/algo-build-loop`) aren't updated yet.
  The plan's follow-up section lists the changes.
- **This PR isn't judged by its own gate.** `master` has no judge yet, so
  the CI job skips with a notice (it would otherwise let the branch judge
  itself), and this PR is reviewed by hand. Merge it with a merge or
  rebase-merge (not a squash) to keep the separate commits. Every later PR,
  including the fixes for the open findings, is judged by `master`'s copy.
- **The `master` ruleset isn't applied.** Run
  `tools/github/apply_ruleset.sh --apply` after merging, so the `verify` check
  already exists.
