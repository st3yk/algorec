# Build Log: agent guardrails

- **Plan**: `design/agent-guardrails/plan.md`
- **Branch**: `feat/agent-guardrails` (base `master` @ `fb5e54c`)
- **Build / test**: `bazel build //...` · `bazel test //...` (once M4 lands: `tools/verify`)

This log is the session's memory. Read it first when resuming. Update "Current state" before every long-running command and at every milestone boundary.

## Current state

- **Milestone / round**: M1+M2 committed, review round 1 running; M3 in progress
- **Last green commit**: `ac1357a` (14/14 tests pass)
- **Waiting on**: M1+M2 reviewer subagent
- **Next action**: M3 (test tiers), then act on the M1+M2 verdict
- **Blockers**: none

## Milestones

- [ ] **M1: lint and types** (plan steps 1, 2)
  - Acceptance: 1. `bazel test //tools/lint/...` passes on the branch. 2. An unused import in `steerrec/items.py` fails `//tools/lint:ruff_check` with the file and line. 3. A `str` passed where a float is expected, in a call inside `steerrec/`, fails `//tools/lint:mypy`. 4. All existing tests still pass.
- [ ] **M2: conventions and proto contract** (plan steps 3, 4)
  - Acceptance: 1. `//tools/conventions:test` passes on the branch. 2. Self-tests: one violating fixture per rule, each producing that rule's message. 3. `//proto:compat_test` fails on a renumbered, reused, removed-not-reserved or retyped field, and passes on an added field.
- [ ] **M3: test tiers and flakiness** (plan step 5)
  - Acceptance: 1. `bazel test //... --config=fast` passes in < 20 s with a warm cache. 2. The 300-item optimality test no longer depends on the 2 s default, and the default is checked in a separate `timing` test. 3. `--runs_per_test=10` on the property tests passes.
- [ ] **M4: branch checks and `tools/verify`** (plan steps 6–10)
  - Acceptance: 1. The self-tests for `docs_changed`, `commits` and `guardrails` fail once per rule. 2. `tools/verify --fast` passes on the branch. 3. The gate refuses a dirty tree (ERROR), runs on a clean worktree at the SHA, and loads the checks from the merge-base. 4. A branch that loosens the commit checker still has its bad commit rejected, and gets NEEDS_HUMAN. 5. The report names the SHA and a reproduce command. 6. `pr_body.py` produces a body where every hash exists on the branch.
- [ ] **M5: agent-side guardrails and orchestration** (plan steps 11–15)
  - Acceptance: 1. `.claude/settings.json` denies pushing to master, `--no-verify`, `gh pr merge` and edits to guardrail files. 2. The PostToolUse hook rejects an inline comment in < 2 s. 3. The Stop hook blocks on a failing `--fast`. 4. The git hooks reject a non-conventional commit subject. 5. AGENTS.md has an "Agent workflow" section. 6. `start_build.sh --dry-run` prints the steps it would take.
- [ ] **M6: CI and drill** (plan steps 16, 18–22)
  - Acceptance: 1. `.github/workflows/verify.yml` runs `tools/verify` and exits with its code. 2. `tools/verify_drill.sh` passes every row that can run locally. 3. The ruleset is applied by a script you run yourself.

Step 17 (dogfood run) is out of scope for this branch. It needs the merged pipeline and the updated skills.

## Research notes

- `ruff` 0.16.9 from PyPI: under rules_python the wheel's executable is at `<wheel repo>/bin/ruff` and reaches runfiles only through `@pypi//ruff:data`. `ruff.__main__.find_ruff_bin()` doesn't look there, so `tools/lint/ruff.py` resolves it as `Path(ruff.__file__).parents[2] / "bin" / "ruff"`.
- A lint `py_test` must be given explicit file lists (`$(rootpaths …)`). Walking the runfiles tree picks up rules_python's generated `*_stage2_bootstrap.py`, and mypy rejects the `*.runfiles` directory name.
- mypy 2.3.1 is compiled and runs in ~2 s over `steerrec/` and `tools/`.
- `gh` is now 2.101.0, so `gh pr checks --watch` is available.
- System Python is 3.10, so scripts run outside Bazel (`tools/verify` and the hooks) must stay 3.10-compatible: no `tomllib`.

## Plan deviations

| Plan step | Deviation | Why | Design-level? |
|---|---|---|---|
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
