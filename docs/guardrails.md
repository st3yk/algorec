# Guardrails: how a change is judged

Every check that decides whether a change is good lives in this repository.
`tools/verify` runs all of them and returns one verdict. Agents, git hooks, CI
and humans run the same command and get the same answer.

## The judge: `tools/verify`

```sh
tools/verify --fast            # inner loop: the working tree, fast tests, coverage
tools/verify                   # the gate: a clean checkout of HEAD, judged by the base's checks
tools/verify --deep            # the gate, plus 5 fresh runs of every test the branch affects
tools/verify --base origin/x   # judge against another base (default: origin/master, then master)
tools/verify --json            # print the JSON report instead of text
```

The exit code is the verdict:

| Exit | Verdict | Meaning |
|---|---|---|
| 0 | `PASS` | Every check passed at this commit, and nothing needs a human. |
| 1 | `FAIL` | At least one check failed. |
| 2 | `NEEDS_HUMAN` | Every check passed, but the branch changes a guardrail, weakens a test, uses a `Docs-Unchanged:` escape, or was judged by its own checks. Only a human can accept it. |
| 3 | `ERROR` | The judge couldn't run: uncommitted changes, an unknown base, or Bazel crashed. Never read it as PASS. |

Each run writes `.verify/reports/<sha>.json` and `.md` (ignored by git). The
report names the commit, the base, the merge-base, the judge, each check's
status and time, every finding, and the command that reproduces it.

### What the gate runs

1. **clean-tree**: tracked files must be committed. The verdict is about a
   commit, not a working tree (untracked files are fine; they aren't in the
   checkout).
2. **base**: the base must resolve and share history with HEAD, and must
   leave something to judge. `--base HEAD`, or any base that already
   contains HEAD, is ERROR, not an empty PASS.
3. **commits**, **docs**, **guardrails**: git-level checks over
   `merge-base..HEAD` (below).
4. **build**, **test** and **evidence**: `bazel build //...` and
   `bazel test //... --config=verify` (every tier, no retries), in a clean
   checkout of HEAD, then the runtime evidence check: every test function in
   the head's test files must have passed (see "What the judge still trusts").
5. **coverage**: every tracked file must be in `//:repo_files`, every tracked
   `.py` file must be linted, and every `.py` file in `steerrec/` and `tools/`
   must be type-checked. A Bazel glob stops at package boundaries, so a new
   package that nobody adds to these lists would otherwise be invisible. The
   check asks Bazel which files the checks' input filegroups actually produce
   (`bazel cquery --output=files` on `//:repo_files` and on the `py_srcs`
   groups that lint and mypy read), not which files they depend on.
6. **demo**: `bazel run //steerrec:demo -- --sweep-only` exits 0.
7. **base-guardrails**, only if the branch changes a guardrail file: the
   base's copies of the guardrail files are put back into the checkout and
   the tests run again, with the verify flags given explicitly (the base's
   `.bazelrc` may not define `--config=verify`). If Bazel rejects the branch
   there (build, test or configuration failure), the verdict is NEEDS_HUMAN:
   the branch passes only by its own rules.
8. **flakes**, with `--deep`: every test target that depends on a changed
   file runs 5 more times, uncached.

The clean checkout is a git worktree in
`~/.cache/steerrec-verify/<repo hash>/wt` (or `$STEERREC_VERIFY_DIR`). Its path
is fixed, so Bazel's analysis cache stays warm between runs, and a lock file
serializes gates on the same repository.

### Who judges

The `tools/verify` entry script (bash, no Python) extracts `tools/verify_lib/`
(and the stdlib-only contract listing it uses) from the **merge-base** and
runs that copy. A branch can't loosen the commit, docs or guardrail rules that
judge it. `--fast` always uses the working tree's own copy.

The judge then checks its own identity: it compares its files byte for byte
with the merge-base's `tools/verify_lib/` and writes the result into the
report's `judge` line. Any mismatch (the base has no judge yet, or the judge
running is the checkout's own copy or a modified one) adds a NEEDS_HUMAN
finding.

That check can't protect against a branch that replaces **both** the entry
script and the judge, because then the branch's code writes the report. So a
local `tools/verify` PASS on a branch that touches `tools/verify` or
`tools/verify_lib/` means nothing on its own. Run the base's entry script
instead:

```sh
git show origin/master:tools/verify | bash -s -- --base origin/master
```

or rely on CI, which extracts the base's judge in its own YAML. Both cases
are tested end to end by `//tools/verify_lib:gate_selftest`, on scratch
repositories with a stub `bazel`.

### What the judge still trusts

Even the base's judge **runs the branch's code**: its tests, BUILD files and
Bazel setup. It narrows what a branch can fake, but it can't rule it out:

- **Pinned Bazel.** The judge runs Bazel with `BAZELISK_SKIP_WRAPPER=1`, so a
  `tools/bazel` wrapper is ignored, and with the merge-base's `.bazelversion`.
- **Runtime evidence.** Every test function in the head's test files must have
  a passed JUnit result from this run (the `evidence` check). The root
  `conftest.py` makes pytest write those results where Bazel asks, and every
  pytest target lists it in `data`. Test logs are deleted before the run, so
  old results can't stand in. A test that exits early, is skipped by any
  spelling, or never runs fails the gate.
- **Flagged setup files.** Changes to `tools/bazel`, `.bazelversion`,
  `.bazeliskrc`, `MODULE.bazel`, any `.bzl` file, any `conftest.py`, or the
  `load()` lines of an existing BUILD file are NEEDS_HUMAN.

What remains is a branch that changes one of those flagged files to fake the
results, or a test that runs and passes but checks nothing. The first is
always NEEDS_HUMAN, the second is what the adversarial reviewer and the human
merging the PR are for.

### PR descriptions: `tools/pr_body`

```sh
tools/pr_body <slug> [--base origin/master] [--report .verify/reports/<sha>.json]
```

It prints a pull request description for the current branch. The facts come
from tools: the verdict and report of the gate run for HEAD (it says "stale",
"not run" or "wrong base" when there is no report for HEAD against the same
merge-base), the commit table from git (with
review-fix commits marked), the review rounds from
`design/<slug>/review-log.md`, and the plan deviations from
`design/<slug>/build-log.md`. Only the prose comes from the author: the
`## Summary`, `## Why` and `## Not done` sections of
`design/<slug>/summary.md`. A missing section says so instead of staying
empty. Any backticked hash in the body that isn't a commit in this
repository is marked "not a commit here".

## Branch checks

| Check | FAIL | NEEDS_HUMAN |
|---|---|---|
| `commits` | A subject that isn't `type(scope): summary` (git's own `Revert "type: …"` subject is accepted) (types: feat, fix, test, refactor, build, chore, docs, perf, style, ci, revert), starts with a capital, or is over 72 characters; a WIP or `fixup!` commit; a merge commit; a lock-file change mixed with other files. | |
| `docs` | A `feat`, `fix`, `perf` or `revert` commit that changes a source in `tools/verify_lib/docs_map.json` (Python modules, `.proto` files, `tools/verify`, `.claude/` and `.github/`; not BUILD files or the golden) without changing its docs page in the same commit. | The same, with a `Docs-Unchanged: <reason>` trailer. The reason goes into the report. |
| `guardrails` | The contract golden breaks against the base's golden, or was deleted. | A guardrail file changed (`tools/verify`, `tools/pr_body`, `tools/verify_drill`, `tools/setup.sh`, `tools/github/`, `tools/verify_lib/`, `tools/conventions/`, `tools/lint/`, `tools/proto_compat/`, `tools/hooks/`, `tools/githooks/`, `tools/agent/`, any `conftest.py`, `tools/bazel`, `.bazelversion`, `.bazeliskrc`, `MODULE.bazel`, any `.bzl` file, `ruff.toml`, `mypy.ini`, `pytest.ini`, `.bazelrc`, `.claude/settings.json`, `.github/`, `CODEOWNERS`). A test function that gains a `return`. Module-level code added to a test file other than imports, definitions and plain assignments (an `if`, a `raise`, or an assignment that mentions `pytest`, `mark`, `skip` or `xfail`). A change to the `load()` lines of an existing BUILD file. In test files (everything under `tests/`, `conftest.py`, `test_*.py`, `*_test.py`, `*_selftest.py`): a function removed or renamed (test or helper); an `assert`, `pytest.raises` or `pytest.approx` removed or changed in any function; a decorator such as `parametrize` removed or changed; a skip or xfail added (also through `from pytest import mark`); a module-level assignment removed or changed, such as a tolerance constant; a module-wide `pytestmark` added. In BUILD files: a `py_test` rule removed, tagged `manual`, or changed in how it runs (`env`, `args`, `main`, `srcs`, …). A line removed from the golden. |

Functions are compared by name across all test files, and asserts by their
normalized source, so moving a test or reformatting an assert isn't a
finding. Renames are compared as a delete plus an add (`--no-renames`), so a
renamed test file keeps its protection. Skips are found in decorators and calls, not in strings. Guardrail
file changes are reported once per area (for example `tools/verify_lib/`). `style`, `refactor`, `test`, `build`, `chore`, `docs` and `ci`
commits claim no behavior change, so `docs` doesn't apply to them; the
reviewer checks that claim.

`tools/verify_lib/` runs under the system Python (3.10 or newer), so it uses
only the standard library, and ruff checks it with `target-version = py310`.
Its rules are tested by `//tools/verify_lib:selftest` on scratch git
repositories.

## On GitHub: the `verify` workflow

`.github/workflows/verify.yml` runs the same judge on every pull request, every
push to `master`, and on demand. It adds no checks of its own.

1. It checks out the PR's head commit (not GitHub's merge commit) with full
   history, and restores the Bazel caches with `bazel-contrib/setup-bazel`.
2. It extracts `tools/verify_lib/` from the merge-base **itself**, in YAML,
   and runs that copy, so a PR that edits `tools/verify` can't change the
   judge. The base is the PR's base branch, the previous `master` commit on a
   push, and the default branch on a manual run.
3. The Markdown report goes into the job summary, and the JSON and Markdown
   reports are uploaded as the `verify-report` artifact.
4. The check is green only on `PASS`. `FAIL`, `NEEDS_HUMAN` and `ERROR` are
   red; the error annotation says which.

It has read-only permissions and uses no secrets, so pull requests from forks
are safe to run. Third-party actions are pinned by commit SHA.

**Its limit:** on `pull_request`, GitHub runs the workflow file **from the PR's
branch**. A PR that edits `verify.yml` can make the `verify` check green
without running the judge. The judge flags a workflow edit as NEEDS_HUMAN,
but only if the workflow still runs it. CODEOWNERS only labels such PRs;
it isn't enforced, because the ruleset requires no reviews. So until the
workflow moves to `pull_request_target` (the base's YAML, checking out the
head SHA read-only), **a green check on a PR that touches `.github/` is not
evidence**: read the diff. That's acceptable while only the owner merges.

### Protecting `master`

`tools/github/apply_ruleset.sh` prints the ruleset in
`tools/github/ruleset.json`; with `--apply` it creates or updates it on the
repository. The ruleset requires a pull request and a green `verify` check
(on an up-to-date branch), blocks force-pushes and deletion, and requires
linear history. The required check must come from GitHub Actions
(`integration_id` 15368), so a commit status posted through the API doesn't
count. The repository admin can bypass the ruleset **only through a pull
request** (`bypass_mode: pull_request`): that is how a NEEDS_HUMAN change is
merged on purpose, and it means even the admin's credentials can't push to
`master` directly. Agents are never given `gh pr merge`.

## The drill: `tools/verify_drill`

```sh
tools/verify_drill [--only <text>] [--keep]
```

It proves the guardrails catch what they claim. It clones the committed HEAD
into a temporary directory (`--no-hardlinks`), makes that commit the base,
and for each planted fault creates a branch, applies the fault, commits it,
and runs `tools/verify --base drill-base`. Where a hook should catch the fault
first, it runs that hook too and expects it to reject. It exits 1 if any row
differs from the table. Run it after every guardrail change.

| Planted fault | Earliest catch | Gate verdict |
|---|---|---|
| (control) a docs-only change | | PASS |
| Inline `#` comment in `steerrec/` | PostToolUse hook | FAIL |
| Function docstring | PostToolUse hook | FAIL |
| New test file without a `py_test` rule | conventions test | FAIL |
| `feat` change to `targets.py` without its docs page | `docs` | FAIL |
| The same, with a `Docs-Unchanged:` trailer | `docs` | NEEDS_HUMAN |
| Proto field renumbered | `//tools/proto_compat:test` | FAIL |
| The ILP's "never below neutral" rows removed | "never below neutral" property tests | FAIL |
| Shortfall silently dropped | bounds tests | FAIL |
| Hand-edited lock-file hash | `//:requirements.test` | FAIL |
| One assertion deleted from a test | `guardrails` | NEEDS_HUMAN |
| Commit checker loosened on the branch, subject `update stuff` | the base's judge (the branch's own commit-msg hook runs the loosened code) | FAIL |
| Commit subject `update stuff` | commit-msg hook | FAIL |
| CI workflow edited | `guardrails` | NEEDS_HUMAN |
| New package that no check sees | `coverage` | FAIL |
| Uncommitted change | clean-tree | ERROR |

Not in the drill: agent permission denials (they're enforced by Claude Code,
not by a script), and mutation testing, which isn't implemented.

## Around the agent: hooks and git hooks

These give fast feedback. None of them decides the verdict; `tools/verify` does.

| Hook | Runs | What it does |
|---|---|---|
| Claude Code `PostToolUse` (`Edit`, `Write`) | after each file edit | `tools/hooks/run post_edit`: ruff and the convention rules on that one file. Problems go straight back to the agent (exit 2). About 0.1 s: it calls the ruff binary directly, found once through `bazel info output_base` and cached in `.verify/ruff-path`. |
| Claude Code `PreToolUse` (`Bash`) | before each shell command | `tools/hooks/run pre_bash`: rejects `git push` with a `+` or `:` refspec, `--force*`, `--mirror`, `--all`, `--delete`, `--prune`, a destination outside `feat/*`, or no explicit remote and branch (exit 2). |
| Claude Code `Stop` | when the agent tries to finish | `tools/hooks/run on_stop`: runs `tools/verify --fast` unless the working tree is unchanged since its last run (a fingerprint of HEAD, the diff and untracked files). A green result is remembered in `.verify/last-fast-green`; a red one in `.verify/last-fast-red`, so an unchanged red tree is sent back with the cached failure instead of a 20 s re-run. A retry (`stop_hook_active`) is let through, so it can't loop. |
| Claude Code `SessionStart` | at session start and resume | `tools/hooks/run session_start`: prints the branch, `git status`, and the "Current state" of every `design/*/build-log.md`. |
| git `commit-msg` | each commit | The gate's `commits` rules on the message being written. |
| git `pre-commit` | each commit | ruff and the convention rules on the staged Python files (it reads the working copy of each staged file). |
| git `pre-push` | each push | Refuses a push to `master` or `main`, or of a commit other than HEAD, then runs the gate on HEAD. `PASS` and `NEEDS_HUMAN` push; `FAIL` and `ERROR` don't. |

Enable the git hooks once per clone with `tools/setup.sh`
(`core.hooksPath = tools/githooks`). The Claude Code hooks are in
`.claude/settings.json`.

Each hook finds its repository from the event (the edited file's path, or the
session's `cwd`) with `git rev-parse --show-toplevel`, not from
`$CLAUDE_PROJECT_DIR`, so it checks the right tree inside a worktree. The hook
scripts run under the system Python (3.10 or newer), use only the standard
library, and are tested by `//tools/hooks:selftest`.

## Agent permissions: a speed bump, not a boundary

`.claude/settings.json` allows the commands the build loop needs and denies
some that it never should (pushing to `master`, force pushes, `--no-verify`,
`gh pr merge`, editing lock files, the golden and the guardrail files). The
Claude Code docs are explicit that Bash rules match the command as written,
not the program: another spelling of the same command isn't matched. And
`bazel test`, `bazel run`, `tools/verify` and the git hooks all execute code
from the branch, so an agent that wants to edit a denied file can do it
through them. The rules stop honest mistakes and make the intended path the
easy one. What actually protects `master` is the ruleset, and what actually
judges a change is `tools/verify` run by the base's entry script or by CI.

## Starting a build: `tools/agent/start_build.sh`

```sh
tools/agent/start_build.sh <slug> [--gate] [--dry-run] [--base origin/master]
```

It takes a finished plan in `design/<slug>/plan.md` and:

1. creates the worktree `.claude/worktrees/<slug>` on a new branch
   `feat/<slug>` from `origin/master`;
2. commits the design folder (`docs(design): add the <slug> plan`), pushes,
   and opens a **draft** PR whose body comes from `tools/pr_body`;
3. unless `--gate`, starts `claude -p "/algo-build-loop design/<slug>/plan.md
   --autonomous" --permission-mode acceptEdits` in the background, logging to
   `~/.cache/steerrec-agent/<slug>.log`.

`--dry-run` prints every command instead of running it. The script refuses an
existing branch or worktree.

## Lint and format

| Target | What it checks |
|---|---|
| `//tools/lint:ruff_check` | `ruff check` over `steerrec/`, `tests/` and `tools/`, with the rules in `ruff.toml`. |
| `//tools/lint:ruff_format_check` | `ruff format --check`: the code is formatted as ruff would format it. |
| `bazel run //tools/lint:fix` | Applies ruff's safe fixes and formatting to the whole repository. |
| `bazel run //tools/lint:ruff -- <args>` | Runs the locked ruff binary on anything, from the repo root. |

`ruff.toml` selects `E,F,W,I,B,UP,ERA`, with three rules switched off:
- `E501`, because the formatter owns line length (120);
- `E731`, because assigned lambdas are used in the core;
- `B905`, because `zip(strict=)` would add runtime checks to the assembler.

Because inline comments aren't allowed, there is no `# noqa`. Exceptions go into
`[lint.per-file-ignores]` in `ruff.toml`.

The ruff binary comes from the locked PyPI wheel (`@pypi//ruff:data`), so its
version is pinned like any other dependency.

## Types

`//tools/lint:mypy` runs mypy over `steerrec/` and `tools/` with `mypy.ini`.
Every function in `steerrec/` must be fully annotated (`disallow_untyped_defs`).
Tests aren't type-checked. mypy sees the real numpy, protobuf (via
`types-protobuf`) and pytest types; only scipy, which ships no stubs for
`scipy.optimize`, is treated as untyped.

## Conventions

`//tools/conventions:test` checks the AGENTS.md rules that a machine can check,
over every file in the repository (`//:repo_files`):

| Rule | What fails |
|---|---|
| `no-comments` | A `#` comment in `steerrec/`, `tests/` or `tools/` Python files. A shebang on line 1 is allowed. |
| `no-docstrings` | A function or class docstring, including an empty one. |
| `no-bare-strings` | A string statement anywhere but the module docstring: a second module string, or a string used as a comment inside code. |
| `module-docstring` | A file in `steerrec/` or `tools/` with no module docstring, or one that names no `docs/` page. Test files and empty `__init__.py` files are exempt, since `docs/testing.md` documents the tests. |
| `doc-ref-exists` | A module docstring names a `docs/…` page (or `NORTH_STAR.md`, `BUILDING.md`, `AGENTS.md`) that doesn't exist. |
| `py-test-rule` | A `tests/test_*.py` file that isn't in the `srcs` of a `py_test` in `tests/BUILD.bazel`, or only in one tagged `manual`. The BUILD file is parsed, not searched, so a `py_library` or a commented-out rule doesn't count. |
| `pytest-footer` | A test file that doesn't end with the pytest footer. |
| `md-link` | A relative link or image to a missing file, or to a `#anchor` that no heading produces. It covers inline links (with titles and `<…>` destinations), images, reference definitions, and repo-root paths (`/docs/…`). Anchors follow GitHub's slug rules, for ATX headings (closing `#`s allowed) and setext headings. Links in code spans and fenced blocks are ignored. Link text that spans lines is not checked. |

Every failure prints the file, the line, and the rule it breaks. The rules are
tested by `//tools/conventions:selftest`, with one violating fixture per rule.

A new Bazel package must add its `all_files` filegroup to `//:repo_files`, and
its `py_srcs` to `//tools:py_srcs` if it's under `tools/`. Otherwise its files
aren't checked, and links to them don't resolve.

## Service contract compatibility

`//tools/proto_compat:test` flattens the descriptor set of
`//proto:recommender_proto` into one line per file syntax, service, RPC, message,
oneof, field (with its JSON name and oneof), enum value and reservation. It compares that listing with `proto/recommender.fields.golden`.

| Change | Result |
|---|---|
| A field or enum value moved to another number | Fails (breaking). |
| A field removed without `reserved` for its number | Fails (breaking). |
| A reserved number or name reused, or a reservation dropped | Fails (breaking). |
| A field's name, label or type changed | Fails (breaking). |
| A message or enum removed | Fails (breaking). |
| An RPC removed, or its request, response or streaming changed; a service removed | Fails (breaking). |
| A field moved into or out of a oneof, or its JSON name changed | Fails (breaking). |
| The file's syntax or edition changed | Fails (breaking). |
| A new RPC | Compatible (golden update needed). |
| A new field, value, message or reservation | Fails until the golden is updated: `bazel run //tools/proto_compat:update_golden`. |

`update_golden` refuses to write when the change is breaking, so the golden can
only grow. Don't edit the golden by hand.
