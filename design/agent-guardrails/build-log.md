# Build Log: agent guardrails

- **Plan**: `design/agent-guardrails/plan.md`
- **Branch**: `feat/agent-guardrails` (base `master` @ `fb5e54c`)
- **Build / test**: `bazel build //...` · `bazel test //...` (once M4 lands: `tools/verify`)

This log is the session's memory. Read it first when resuming. Update "Current state" before every long-running command and at every milestone boundary.

## Current state

- **Milestone / round**: M1–M6 committed; M3+M4 round-1 fixes committed; final review round (M3+M4 round 2, M5+M6 round 1, settings.json draft) next
- **Last green commit**: `f95acfb` (every commit since `d2fcfdd` passes `bazel test //... --config=fast` on its own)
- **Waiting on**: nothing
- **Next action**: drill + gate on HEAD, final review, then commit `.claude/settings.json` last (its deny rules block edits to guardrail files), push, open the PR
- **Blockers**: none

## Milestones

- [x] **M1: lint and types** (plan steps 1, 2)
  - Acceptance: 1. `bazel test //tools/lint/...` passes on the branch. 2. An unused import in `steerrec/items.py` fails `//tools/lint:ruff_check` with the file and line. 3. A `str` passed where a float is expected, in a call inside `steerrec/`, fails `//tools/lint:mypy`. 4. All existing tests still pass.
- [x] **M2: conventions and proto contract** (plan steps 3, 4)
  - Acceptance: 1. `//tools/conventions:test` passes on the branch. 2. Self-tests: one violating fixture per rule, each producing that rule's message. 3. `//proto:compat_test` fails on a renumbered, reused, removed-not-reserved or retyped field, and passes on an added field.
- [x] **M3: test tiers and flakiness** (plan step 5)
  - Acceptance: 1. `bazel test //... --config=fast` passes in < 20 s with a warm cache. 2. The 300-item optimality test no longer depends on the 2 s default, and the default is checked in a separate `timing` test. 3. `--runs_per_test=10` on the property tests passes.
- [x] **M4: branch checks and `tools/verify`** (plan steps 6–10)
  - Acceptance: 1. The self-tests for `docs_changed`, `commits` and `guardrails` fail once per rule. 2. `tools/verify --fast` passes on the branch. 3. The gate refuses a dirty tree (ERROR), runs on a clean worktree at the SHA, and loads the checks from the merge-base. 4. A branch that loosens the commit checker still has its bad commit rejected, and gets NEEDS_HUMAN. 5. The report names the SHA and a reproduce command. 6. `pr_body.py` produces a body where every hash exists on the branch.
- [x] **M5: agent-side guardrails and orchestration** (plan steps 11–15)
  - Acceptance: 1. `.claude/settings.json` denies pushing to master, `--no-verify`, `gh pr merge` and edits to guardrail files. 2. The PostToolUse hook rejects an inline comment in < 2 s. 3. The Stop hook blocks on a failing `--fast`. 4. The git hooks reject a non-conventional commit subject. 5. AGENTS.md has an "Agent workflow" section. 6. `start_build.sh --dry-run` prints the steps it would take.
- [x] **M6: CI and drill** (plan steps 16, 18–22)
  - Acceptance: 1. `.github/workflows/verify.yml` runs `tools/verify` and exits with its code. 2. `tools/verify_drill.sh` passes every row that can run locally. 3. The ruleset is applied by a script you run yourself.

Step 17 (dogfood run) is out of scope for this branch. It needs the merged pipeline and the updated skills.

## Research notes

- `ruff` 0.16.9 from PyPI: under rules_python the wheel's executable is at `<wheel repo>/bin/ruff` and reaches runfiles only through `@pypi//ruff:data`. `ruff.__main__.find_ruff_bin()` doesn't look there, so `tools/lint/ruff.py` resolves it as `Path(ruff.__file__).parents[2] / "bin" / "ruff"`.
- A lint `py_test` must be given explicit file lists (`$(rootpaths …)`). Walking the runfiles tree picks up rules_python's generated `*_stage2_bootstrap.py`, and mypy rejects the `*.runfiles` directory name.
- mypy 2.3.1 is compiled and runs in ~2 s over `steerrec/` and `tools/`.
- `gh` is now 2.101.0, so `gh pr checks --watch` is available.
- `git clone --local` into the scratchpad fails with "Invalid cross-device link"; use `--no-hardlinks`, and `set -e` in drill scripts (a failed clone once let drill commands run in the main repo; the two local drill branches were deleted, the feature branch was untouched).
- The first gate run (fcee819) found 4 bugs in the judge itself: docs map too broad for proto/, skip detection in strings, noisy guardrail list, base-guardrails ERROR on a base .bazelrc without `--config=verify`. Fixed in d288cdb and 4135b5b.
- System Python is 3.10, so scripts run outside Bazel (`tools/verify` and the hooks) must stay 3.10-compatible: no `tomllib`.

## Plan deviations

| Plan step | Deviation | Why | Design-level? |
|---|---|---|---|
| 6 | `docs` applies per commit and only to feat/fix/perf/revert commits, not to the whole branch | AGENTS.md says "in the same commit", and style/refactor/test/build commits claim no behavior change; a branch-wide rule would fail every mechanical commit. | No |
| 6 | `guardrails` compares test functions and asserts through the AST, not diff lines | Line diffs flag every reformat and move; normalized asserts don't. | No |
| 6 | Collected-test counts (`pytest --collect-only` at base vs head) are not compared | That needs two full builds; removed functions, asserts, parametrize changes and skips are caught statically instead. | No |
| 7 | `--fast` runs `bazel test //... --config=fast`, not an rdeps-selected target set | Bazel's cache already re-runs only affected tests; an rdeps query adds cost and a failure mode for no gain. | No |
| 8 | The gate worktree lives in `~/.cache/steerrec-verify/<repo hash>/wt`, reports in `.verify/reports/` | `bazel-out` is a symlink into Bazel's output tree; a fixed worktree path keeps Bazel's analysis cache warm. | No |
| 8 | The gate runs the branch's own guardrails, then a second pass with the base's guardrail files overlaid, instead of only the base's | Overlaying alone breaks a legitimate guardrail PR's build and hides whether the branch passes at all; two passes give FAIL vs NEEDS_HUMAN. | No |
| 9 | `--deep` has flake re-runs only; mutation testing (mutmut) is not implemented | It needs a separate venv outside Bazel and minutes per module; left as a follow-up and stated in the PR. | No |
| 12 | The Stop and PostToolUse hooks report problems; they never reformat files themselves | An edit made behind the agent's back invalidates its view of the file. | No |
| 13 | pre-commit checks the working copy of each staged file, not the staged blob | Simpler and fast; the gate checks the commit anyway. | No |
| 18 | CI doesn't add a `needs-human` label | That needs a write token; a NEEDS_HUMAN run is red with an error annotation, and the job summary lists the reasons. | No |
| 21 | The build loop's CI wait is not implemented in this repo | It belongs to the build-loop skill update (plan follow-up). | No |
| 11 | `.claude/settings.json` is committed last | Its deny rules block edits to guardrail files, including by this build session. | No |
| 10 | pr_body lives in `tools/verify_lib/pr_body.py`, prose comes from `design/<slug>/summary.md` | Keeps facts tool-generated and prose clearly separated. The `.github` PR template comes with M6. | No |
| 1 | A hand-rolled wrapper around the wheel's binary instead of `aspect_rules_lint` | It needs no new Bazel module, and the spike worked. | No |
| 1 | `E501`, `E731` and `B905` are ignored | The formatter owns line length. Assigned lambdas are used in the core. `zip(strict=)` would add runtime checks to the assembler, which is a behavior change. | No |
| 1 | `F401` is ignored in `tests/test_toolchain.py` via `per-file-ignores` | The import of `milp` is the test. `# noqa` isn't possible under the no-comments rule. | No |
| 4 | Targets are `//tools/proto_compat:test` and `:update_golden`, not `//proto:compat_test` | `py_test` sources must live in their own package, and proto/ holds no Python. | No |
| 3 | Test files may omit the module docstring | Five of six test files have none, and docs/testing.md documents each test file. | No |
| — | Milestones are reviewed in pairs (M1+M2, M3+M4, M5+M6) | Keeps reviewer cost down; each pair is still reviewed against its own acceptance checks. | No |
| 2 | `Solver` is now `Callable[..., Any]` instead of `Callable[..., object]` | mypy can't see `.status`/`.x` on `object`. No runtime effect. | No |

## Decisions

- D1: design and build logs are committed under `design/<slug>/` (the plan's recommendation).
- D2: no human gate between design and build by default.
- D3: `--deep` is not part of the gate. It's required before "ready" once mutation testing exists.
