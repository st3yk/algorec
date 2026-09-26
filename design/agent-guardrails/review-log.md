# Build Review Log: agent guardrails

A record of every milestone's adversarial review rounds, kept so anyone can see what each reviewer found and what was done about it.

## M1+M2 — lint, types, conventions, proto contract · Round 1

**Reviewed**: `fb5e54c..1119666` · **Verdict**: blocker=0, major=2, minor=6, nit=4 → ITERATE

| Severity | Finding (file:line / commit) | Action (fix commit / declined — why) |
|---|---|---|
| major | New Bazel packages (e.g. `steerrec/serving/`) are invisible to lint, mypy and the conventions test; the package lists in `//:repo_files` and `//tools:py_srcs` are hand-maintained | Fixed in M4: `tools/verify` runs a `coverage` check that compares `git ls-files` with what `//:repo_files` and the lint targets see, and fails on any tracked file no check covers. A Bazel glob can't cross packages, so the check has to live outside Bazel. |
| major | `tools/proto_compat/compat.py`: no services, RPCs, oneofs, `json_name` or syntax; deleting an RPC passed | Fixed in `ffe9af0` |
| minor | Markdown link checker: titles, `<…>`, reference links, images, nested text, nested fences, closing-hash and setext headings, root paths | Fixed in `97d253e` (multi-line link text is still unchecked, documented) |
| minor | Bare string statements, a second module string and empty docstrings pass | Fixed in `97d253e` (`no-bare-strings` rule) |
| minor | `py-test-rule` is a regex: `py_library`, `manual` and commented-out rules count | Fixed in `97d253e` (BUILD parsed with `ast`) |
| minor | mypy sees numpy/scipy/protobuf as `Any` | Fixed in `cf57bf7`, `ceffb8c`; it caught a real `str | None` bug in `update_golden` |
| minor | The golden can be hand-edited in the same diff as a breaking proto change | Fixed in M4: the gate compares the golden with the merge-base golden using `breaking_changes`, and any golden line removal is NEEDS_HUMAN |
| minor | Flaky / near-timeout tests (`test_synthetic` 56 s at `size = "small"` under load) | Fixed in M3 (`05abfc4`): slow tiers are `size = "medium"`, the timing test is `exclusive`, and `--runs_per_test=10` passes |
| nit | `f917c43` fixes earlier commits on the branch; should be squashed | Declined: rewriting history isn't possible in this environment, and separate fix commits keep the review trail visible |
| nit | Rule messages don't all name a source or a fix | Fixed in `97d253e` |
| nit | Non-obvious choices only in the build log, not `docs/decisions.md` | Fixed in `21864f8` |
| nit | Any `#!` line 1 comment is exempt; golden compared as an ordered list | Golden: fixed in `ffe9af0`. Shebang: declined, `#!` on line 1 is a shebang by definition |

Also found while fixing: `ffe9af0`–`ceffb8c` fail `//tools/lint:ruff_format_check` because a file was committed before `lint:fix` reformatted it (fixed in `0ad171f`). Local runs had tested the working copy, not the commit, which is what the M4 gate prevents.

---

## M3+M4 — test tiers, branch checks, tools/verify (and M1+M2 round-1 fixes) · Round 1

**Reviewed**: `1119666..673495b` · **Verdict**: blocker=1, major=5, minor=6, nit=2 → ITERATE

| Severity | Finding (file:line / commit) | Action (fix commit / declined — why) |
|---|---|---|
| blocker | The judge loader (`bootstrap.py`) is branch code, so a branch can run its own judge and report "judge: base" (reproduced as PASS) | Fixed in `ecf316a`: bash-only entry extracts the merge-base judge; the judge verifies its own files against the merge-base; docs state that only the base's entry (`git show origin/master:tools/verify \| bash -s --`) and CI can't be fooled by a branch that replaces both entry and judge; `gate_selftest` reproduces both cases |
| major | Rename detection hides a renamed test file's weakened asserts | Fixed in `70a6911` (`--no-renames`) |
| major | `pytestmark`, pytest `-k` in a rule's `env`, tolerance constants, helper-function asserts, `from pytest import mark`, conftest.py all bypass the AST comparison | Fixed in `70a6911` |
| major | Coverage trusts `deps()`; an `output_group` filegroup hides a file from lint and mypy | Fixed in `00f387f` (`cquery --output=files` on the checks' input groups) |
| major | `--base HEAD` / `HEAD~1` produce a PASS that pr_body shows | Fixed in `ecf316a` (ERROR when the base leaves nothing to judge) and `667a102` (pr_body: "wrong base") |
| major | No end-to-end tests of the gate | Fixed in `ecf316a` (`//tools/verify_lib:gate_selftest`, stub bazel on PATH) |
| minor | Git errors surface as FAIL with a traceback | Fixed in `ecf316a` (ERROR report, exit 3) |
| minor | Docs describe controls that aren't built | Fixed in `ecf316a`; settings and CI now exist on the branch |
| minor | pr_body copies non-branch hashes unchecked | Fixed in `667a102` (marked "not a commit here") |
| minor | 300-item test: 60 s budget in a 60 s-timeout target; asserts mean p, not the optimum | Budget fixed in `a24c430`. Exact optimum declined: the pool is too large to brute-force, and a stored constant would pin today's solver rather than optimality; `hit_time_limit is False` already means HiGHS reported optimal within its gap |
| minor | `Revert "feat: x"` rejected | Fixed in `0df90e2` |
| minor | `--flaky_test_attempts=1` doesn't re-run cached passes | Docs fixed in `0982c07`; `--deep` is the flake hunt |
| nit | `git clean` without `-x` leaves ignored overlay files | Fixed in `ecf316a` |
| nit | Docs say `tools/verify*` but the pattern is exact | Fixed in `70a6911` (docs list each entry script) |

Also found by the first full drill run (15/16): the loosened-checker row wrongly expected the branch's own commit-msg hook to reject; fixed in `f95acfb`.

---
