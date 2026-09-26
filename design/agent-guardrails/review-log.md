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
