# Agent guardrails: scripts as the source of truth

## Goal

Make the repository itself decide whether a change is good, through scripts
the skills are required to call. GitHub then runs the **same** script
independently on every PR and blocks merges when it isn't green (Phase 6). CI
adds no checks of its own. It is a second, independent run of the one judge.

1. You start `/algo-design-loop` with an idea.
2. When the plan reaches SHIP, the build starts on its own. You see a draft PR
   on GitHub. It becomes "ready" only when `tools/verify` says **PASS** for the
   exact commit at the PR's head, and the PR body carries that report.

"High trust" means four concrete properties:

- **One judge.** `tools/verify` is the only definition of "good". The skills,
  the hooks, the reviewer subagent and you all run the same command and get
  the same verdict.
- **The judge can't be edited by the judged.** The gate runs the *base
  branch's* copy of the checks against the branch, so a branch can't weaken the
  checks that judge it. Changes to the guardrails give **NEEDS_HUMAN**, never
  PASS.
- **Reproducible verdicts.** The gate runs on a clean checkout of a commit SHA,
  not on the working tree. The report names the SHA, so anyone can re-run it
  and must get the same result.
- **Fast feedback before the gate.** Agents learn about problems seconds after
  the edit, through hooks that call the same checks per file.

## What exists today (baseline, 2026-09-26)

| Area | State |
|---|---|
| Build / test | Bazel 9, hermetic Python 3.12, locked PyPI. `bazel test //...` has 7 targets. With a cold cache it takes ~36 s (critical path `test_assembler`, then `test_synthetic` at ~20 s, and everything else under 5 s). |
| Lock freshness | `//:requirements.test` already fails on a stale lock. |
| Conventions (AGENTS.md) | No inline comments or docstrings, docs change with code, one `py_test` per file, the test footer, Conventional Commits, no renumbering of proto fields. **Enforced only by the agent reading AGENTS.md.** |
| Lint / format / types | None. |
| Hooks / Claude settings | None (`.claude/` holds only worktrees). |
| Skills | `algo-build-loop` verifies with whatever build and test commands it finds, and its reviewer re-runs them. There is no shared verdict format, no SHA pinning, and nothing stops it from weakening a test. |
| GitHub | `st3yk/algorec` and `st3yk/algorec-skills` are **public** as of 2026-09-26. Actions is enabled, there are no rulesets yet, and there's no `.github/`. The local skills clone still points at `st3yk/skills`, which GitHub redirects: run `git remote set-url origin git@github.com:st3yk/algorec-skills.git`. |
| `gh` | 2.4.0 (2022). It's too old for `gh pr checks --watch`, which Phase 6 depends on. **Upgrade it.** |
| Timing-sensitive test | `test_default_time_limit_solves_a_300_item_pool_to_optimality` depends on a 2 s wall-clock budget. It flakes if the machine is loaded, for example while a reviewer subagent runs tests in parallel. |

## Decisions you need to make

| # | Decision | Recommendation |
|---|---|---|
| D1 | Where design and build logs live | **Commit them under `design/<slug>/`** on the feature branch, so the reviewer and you see the plan the code claims to implement. |
| D2 | Human gate between design and build | **None by default.** The draft PR opens with the plan first, and you can close it to abort. `--gate` stops after the plan-only PR. |
| D3 | Whether `verify --deep` (flake re-runs, mutation testing) is part of the gate | **Yes, restricted to what the branch touched**, if that keeps the gate under ~5 min. Otherwise run it before "ready" only. |

## The contract: `tools/verify`

```
tools/verify --fast            # inner loop: working tree, affected targets, no git checks
tools/verify [--base master]   # the gate: clean worktree at HEAD, judged by base's checks
tools/verify --deep            # the gate + flake re-runs + mutation testing on touched modules
tools/verify --json            # machine output, for the skills and pr_body
```

**Verdicts** (the exit code is the verdict):

| Exit | Verdict | Meaning | What the skill may do |
|---|---|---|---|
| 0 | `PASS` | Every check is green at this SHA, and no guardrail changed. | Push, mark the PR ready. |
| 1 | `FAIL` | At least one check is red. | Fix it. The PR stays a draft. |
| 2 | `NEEDS_HUMAN` | Checks are green, but the branch changed a guardrail, weakened a test, or declared a `Docs-Unchanged:` escape. | The PR stays a draft with the reasons at the top. Only you can accept. |
| 3 | `ERROR` | Verify itself couldn't run (Bazel crash, dirty tree for the gate, unknown base). | Stop and report. Never read it as PASS. |

**The report** is `bazel-out/verify/<sha>.json` plus `<sha>.md`. It holds the
SHA, base SHA, verdict, and per check: name, status, duration, and the first
failing lines. It also holds tool versions, the list of guardrail findings,
and the exact command to reproduce. `pr_body.py` embeds the Markdown version.

**The latency budget:**

| Layer | Runs | Target (warm cache) |
|---|---|---|
| `PostToolUse` hook (per-file checks) | each edit of `.py` / `.proto` / `BUILD` | < 2 s |
| `tools/verify --fast` | each increment, the `Stop` hook, pre-commit | < 20 s |
| `tools/verify` (the gate) | each milestone, before any push | < 3 min |
| `tools/verify --deep` | before "ready" (D3) | < 10 min |

---

## Implementation plan

Each step is one or two commits. "Accept" is the check that proves the step is
done.

### Phase 1: the checks

**Step 1. Lint and format with ruff, as Bazel tests.**
- Add `ruff` to `requirements.in` and re-lock. Configure it in `ruff.toml`:
  rules `E,F,W,I,B,UP,ERA`, with line length matched to the current code.
- Add `//tools/lint:ruff_check` and `//tools/lint:ruff_format_check` as
  `py_test`s over `//steerrec` and `//tests` sources, so they're cached and part
  of `bazel test //...`. `bazel run //tools/lint:fix` applies fixes.
- Put the baseline reformat in its own `style:` commit.
- Research first: whether `aspect_rules_lint` works with Bazel 9 and Bzlmod.
  If it does, it's the more idiomatic choice.
- *Accept:* an unused import in `steerrec/items.py` fails the target and names
  the file and line.

**Step 2. Type checking.** Add `mypy` as a `py_test` over `steerrec/`, with
`--disallow-untyped-defs` (tests exempt).
*Accept:* a `str` passed where `Item.p` expects a float, in a call inside
`steerrec/`, fails the target.

**Step 3. AGENTS.md conventions as a test.**
`//tools/conventions:test` is stdlib-only (`ast` and `tokenize`), with the
repo files as `data`. It checks:
- no `#` comments and no function or class docstrings in `steerrec/` and
  `tests/`;
- exactly one module docstring, and every `docs/...` path it mentions exists;
- every `tests/test_*.py` has a `py_test` rule and ends with the pytest
  footer;
- every relative Markdown link and `#anchor` resolves.

Every failure message quotes the AGENTS.md rule and says how to fix it.
*Accept:* for each rule, a self-test fixture that violates it produces that
rule's message.

**Step 4. Proto contract.** `//proto:compat_test` compares the descriptor of
`//proto:recommender_proto` with a checked-in
`proto/recommender.fields.golden` (one line per field:
`message.field = number type label`). It fails on a renumbered field, a
reused number, a removed field that isn't `reserved`, or a changed type.
New fields are added with `bazel run //proto:update_golden`.
*Accept:* changing a field number fails the test.

**Step 5. Test tiers, and remove flakiness.**
- Tag the heavy property tests `slow`. Split `test_assembler.py` into fast
  cases and `test_assembler_properties`.
- Make the 300-item optimality test pass an explicit, generous
  `time_limit_s` and assert `hit_time_limit is False` plus the optimal
  objective. Keep the check of the 2 s default in a separate test tagged
  `timing` and `exclusive`.
- `.bazelrc`: `--config=fast` (`--test_tag_filters=-slow,-timing`) and
  `--config=verify` (`--test_output=errors`, `--flaky_test_attempts=1`, no
  retries, because a retry would hide exactly the nondeterminism the repo
  promises isn't there).
- *Accept:* `--config=fast` passes in < 20 s with a warm cache, and
  `--runs_per_test=10` on the property tests passes.

**Step 6. Branch checks (they need a base ref, so they're scripts, not Bazel
tests).** They live in `tools/verify_lib/`, each with self-tests on scratch
git repos.
- `docs_changed`: `tools/docs_map.toml` maps each source to its doc page
  (`steerrec/assembler.py → docs/code/assembler.md`,
  `proto/** → docs/service-contract.md`). A mapped source that changed while
  its page didn't gives FAIL. A commit trailer `Docs-Unchanged: <reason>`
  turns it into NEEDS_HUMAN, with the reason in the report.
- `commits`: Conventional Commits with a known type and scope, a subject of
  at most 72 characters, no `WIP`/`fixup!`, and lock-file changes in their own
  commits.
- `guardrails`: NEEDS_HUMAN when the branch:
  - changes a guardrail file (`tools/verify*`, `tools/verify_lib/**`,
    `tools/conventions/**`, `tools/hooks/**`, `ruff.toml`,
    `.claude/settings.json`, `.bazelrc`'s verify config, `.github/**`,
    `CODEOWNERS`);
  - lowers the collected test count for any target (`pytest --collect-only`
    at base vs head);
  - deletes a test function or an `assert`;
  - changes a numeric literal inside an `assert` or `approx` line;
  - adds `skip`, `xfail` or `tags = ["manual"]`.

  Each finding names the file and line and shows the diff hunk.

### Phase 2: `tools/verify`, the judge

**Step 7. `tools/verify --fast`.** Runs on the working tree:
- ruff format and check, and conventions, on the changed files;
- `bazel test --config=fast` over the targets affected by the change
  (`bazel query "rdeps(//..., set(<changed files>))"`), falling back to
  `//...`.

It prints one line per check and trimmed failure logs.
*Accept:* on master, it passes in < 20 s with a warm cache.

**Step 8. `tools/verify` (the gate).**
1. Refuse to run (`ERROR`) if HEAD has uncommitted changes to tracked files.
   The verdict is about a commit, not a working tree.
2. Create a throwaway worktree at `HEAD`'s SHA under `bazel-out/verify/wt`.
   It shares the Bazel disk cache, so it stays fast.
3. **Load the checks from the base.** Extract `tools/verify_lib/`,
   `tools/conventions/` and `ruff.toml` from `git merge-base <base> HEAD`
   into a temp dir, and run *those* against the branch worktree. Tests are
   different: the branch's own tests run, since new tests belong to the
   change, and `guardrails` (Step 6) is what catches weakened ones.
4. Run `bazel build //...`, `bazel test //... --config=verify`,
   `docs_changed`, `commits`, `guardrails`, and the demo smoke run
   (`bazel run //steerrec:demo -- --sweep-only`).
5. Write the report, print the verdict, and exit with its code.

*Accept:* on master with an empty branch, it gives PASS. A branch that edits
`tools/verify_lib/commits.py` to allow any subject still has its bad commit
subject rejected (by base's copy), and gets NEEDS_HUMAN for the guardrail
change.

**Step 9. `tools/verify --deep`.**
- `--runs_per_test=5` on the test targets affected by the branch.
- `mutmut` on the `steerrec/` modules the branch touched, limited to the
  changed functions. Surviving mutants are listed in the report. Whether they
  mean FAIL or NEEDS_HUMAN is decided by D3. Start with NEEDS_HUMAN above a
  threshold.

This is the strongest check against tests that look green but pin nothing,
which is otherwise only caught by a reviewer reading them.
*Accept:* a deliberately vacuous new test (asserting only that the page is
non-empty) is caught through a surviving mutant.

**Step 10. `tools/pr_body.py <slug>`.**
It fills in `.github/pull_request_template.md` from the verify report,
`collect_changes.sh`, `build-log.md` and the review log. The sections are:
- the verdict badge and SHA (top);
- Summary, and Why (link to `design/<slug>/plan.md`);
- changes by milestone;
- NORTH_STAR promises touched and the tests that pin them;
- the verify report;
- review verdicts;
- deviations from the plan;
- NEEDS_HUMAN reasons;
- not done;
- how to try it.

Facts come from tools, and the agent writes only the prose.
*Accept:* every hash in the body exists on the branch, and the SHA in the
badge equals the PR head.

### Phase 3: guardrails around the agent (fast feedback, not the judge)

**Step 11. `.claude/settings.json`, checked in.**
- **Allow:** `bazel *`, `tools/verify*`, `tools/pr_body.py`, read-only git,
  `git add|commit|switch|worktree`, `git push origin feat/*`,
  `gh pr create|edit|view|ready`.
- **Deny:** pushing to `master`, `--force`, `--no-verify`,
  `git reset --hard`, `gh pr merge`, and Edit/Write on lock files,
  `proto/*.golden`, and the guardrail files from Step 6 (including
  `.github/**`).

This doesn't make the gate stronger, since the gate already uses base's
checks. It stops the agent from wasting a milestone on changes that can
only come out NEEDS_HUMAN.
*Accept:* the harness refuses an edit to `tools/verify_lib/commits.py`.

**Step 12. Claude Code hooks.**
- `PostToolUse` (`Edit|Write`) runs per-file ruff and conventions, and exits 2
  with the message. Target < 2 s: it calls the ruff binary directly.
- `Stop` runs `tools/verify --fast` if the tree changed since its last green
  run, and blocks the stop on failure. It honors `stop_hook_active`.
- `SessionStart` prints the branch, `git status --short`, and the build log's
  "Current state" and "Next action".

*Accept:* an agent that adds an inline comment sees the hook message in the
same turn.

**Step 13. Git hooks (optional convenience).** `tools/setup.sh` sets
`core.hooksPath=tools/githooks`: a `commit-msg` check with the `commits` rule,
`pre-commit` running `--fast` on staged files, and `pre-push` running the
gate. They're only a shortcut, since the skills call the gate themselves.

### Phase 4: orchestration

**Step 14. `tools/agent/start_build.sh <slug>`.**
1. Create the worktree `.claude/worktrees/<slug>` on `feat/<slug>` from the
   fetched `origin/master`, and copy in `design/<slug>/`.
2. Commit the plan (`docs(design): add <slug> plan`), push, and open a
   **draft** PR containing only the plan, built with `pr_body.py`.
3. Launch `claude -p "/algo-build-loop design/<slug>/plan.md --autonomous"`
   in the background in the worktree. The log goes to
   `~/.cache/steerrec-agent/<slug>.log`.

Research first: whether skills load in `-p` mode from symlinked
`~/.claude/skills`, and which `--permission-mode` to use (`acceptEdits` plus
the allowlist).
*Accept:* a toy plan gives a draft PR within 1 minute.

**Step 15. AGENTS.md "Agent workflow" section.** This is the interface the
skills discover, so they stay repo-agnostic:

```md
## Agent workflow
- verify-fast: tools/verify --fast
- verify: tools/verify --base master
- verify-deep: tools/verify --deep --base master
- design-dir: design/<slug>/
- start-build: tools/agent/start_build.sh <slug>
- pr-body: tools/pr_body.py <slug>
```

It also documents the verdicts and says that `design/` holds plans and logs,
while `docs/` describes what's built.

### Phase 5: prove it

**Step 16. `tools/verify_drill.sh`.** It applies each planted fault on a
scratch branch and asserts the verdict and the earliest layer that catches
it:

| Planted fault | Earliest catch | Gate verdict |
|---|---|---|
| Inline `#` comment in `steerrec/` | PostToolUse hook | FAIL |
| Function docstring | PostToolUse hook | FAIL |
| New `tests/test_x.py` without a `py_test` rule | `--fast` (conventions) | FAIL |
| `targets.py` changed, its doc not | gate (`docs_changed`) | FAIL |
| The same, with `Docs-Unchanged:` | gate | NEEDS_HUMAN |
| Proto field renumbered | `--fast` (`compat_test`) | FAIL |
| Assembler returns a page below neutral | `--fast` (property test) | FAIL |
| Shortfall silently dropped | `--fast` (bounds tests) | FAIL |
| Hand-edited `requirements_lock.txt` | settings deny, then `//:requirements.test` | FAIL |
| Deleted assertion | gate (`guardrails`) | NEEDS_HUMAN |
| Commit checker loosened on the branch | settings deny, then base's checks | FAIL + NEEDS_HUMAN |
| Commit subject `update stuff` | `commit-msg` / gate | FAIL |
| Vacuous new test | `--deep` (mutant survives) | per D3 |
| Uncommitted change during the gate | gate | ERROR |

*Accept:* every row matches. Re-run the drill after any guardrail change.

**Step 17. Dogfood run.** Put one small real change through the whole
pipeline, for example "scale stage 2's clarity preference by |s|" from the
NORTH_STAR open questions. Record the misses in `docs/decisions.md` and turn
each one into a check and a drill row. Do this after Phase 6, so the run also
exercises the CI wait.

### Phase 6: GitHub runs the judge independently

These steps start only once `tools/verify` exists (Phase 2). None of them adds
a check that `tools/verify` doesn't already have.

**Step 18. `.github/workflows/verify.yml`.**
- Triggers: `pull_request` (opened, synchronize, reopened,
  ready_for_review), `push` to `master`, and `workflow_dispatch`.
- `permissions: contents: read` only. No secrets are used, so fork PRs are
  safe to run.
- It uses `concurrency` per PR with cancel-in-progress, and
  `timeout-minutes: 20`.
- One job, `verify`:
  1. `actions/checkout` with `fetch-depth: 0` (the gate needs the merge-base
     and the commit range).
  2. `bazel-contrib/setup-bazel` with `disk-cache`, `repository-cache` and
     `bazelisk-cache`, keyed on `MODULE.bazel.lock` and
     `requirements_lock.txt`.
  3. `tools/verify --base origin/${{ github.base_ref || 'master' }} --json`
     with `--config=ci` (no `~/.cache` disk-cache path).
  4. Append the Markdown report to `$GITHUB_STEP_SUMMARY`, and upload the
     JSON report and `bazel-testlogs/**/test.xml` as artifacts.
  5. Exit with verify's code. That makes `PASS` green, and `FAIL`, `ERROR`
     and `NEEDS_HUMAN` red. For `NEEDS_HUMAN`, add the label `needs-human`
     with the reasons, so you can tell it apart from a real failure.
- Pin third-party actions by commit SHA. That's cheap supply-chain hygiene
  now that the repo is public.
- *Accept:* a PR with a red test shows a red `verify` check, with the failing
  test in the job summary. A re-run on the same SHA with a warm cache takes
  < 3 min.

**Step 19. Ruleset on `master`** (`gh api repos/st3yk/algorec/rulesets`,
or Settings → Rules):
- require a PR before merging (0 approvals, since you're the only reviewer and
  merging is your approval);
- require the status check `verify`, and require the branch to be up to date;
- block force-pushes and deletion, and require linear history;
- no bypass for anyone except repo admin (you), so a genuine `NEEDS_HUMAN`
  can still be merged deliberately.

Also: keep "Require approval for first-time contributors" for fork workflows
(the default), turn on secret scanning and push protection (free on public
repos), and turn on Dependabot alerts.

*Accept:* `git push origin master` from any clone is rejected. A PR with a
red `verify` shows "Merging is blocked".

**Step 20. Make the workflow hard to tamper with.**
On `pull_request`, GitHub runs the workflow file from the PR's branch, so a
branch could rename a job that always passes to `verify`. For a single-owner
repo, the answer is layered:
- the agent can't edit `.github/**` (Step 11);
- `guardrails` gives `NEEDS_HUMAN` for any `.github/**` change (it's on
  Step 6's list), and the local gate runs the base's checks;
- add `CODEOWNERS` with `.github/ @st3yk` and `tools/verify* @st3yk`, as a
  signal in the PR UI.

If you ever accept outside PRs, move to a `pull_request_target` workflow,
which always runs the base branch's YAML. Check out the PR's head SHA, keep
`contents: read`, and use no secrets. Don't do that before you need it.

**Step 21. Build loop waits for CI** (part of the build-loop skill update).
After each push, the build loop runs `gh pr checks <pr> --watch` for the
pushed SHA:
- **CI and local agree:** continue.
- **CI red, local PASS:** that's an environment leak or a flake. Log it as a
  blocker finding. Reproduce locally with the report's reproduce line, fix it
  as a `fix(ci):` or `fix(test):` commit, and allow at most 3 attempts per
  milestone.
- **CI never started or was cancelled:** re-run once with `gh run rerun`,
  then stop and report.

`gh pr ready` needs **both** a local `PASS` and a green `verify` check at the
PR head SHA. `pr_body.py` adds the CI run link next to the local report.

**Step 22. Drill rows for CI.** Add to Step 16's table:
- a push straight to `master` is rejected by the ruleset;
- a branch that edits `.github/workflows/verify.yml` gets `NEEDS_HUMAN`, the
  `needs-human` label, and is blocked;
- a test that passes locally but depends on something outside the tree (for
  example `$HOME`) shows red in CI only, and the build loop logs the
  mismatch.

**Cost:** $0. Standard Actions runners are free and unlimited for public
repos (Linux: 4 vCPU, 16 GB). The cache limit is 10 GB per repo. The one paid
part would be an AI reviewer in CI (`claude-code-action`), which needs an API
key secret. Leave it out. If you add it later, trigger it only on your own
PRs, never on fork PRs.

---

## Follow-up: update the skills

The skills hold the rules for using the judge. The repo holds the judge.
Both skills read the "Agent workflow" section (Step 15). Without it, they
fall back to today's behavior.

### `/algo-design-loop`

1. **Step 0:** read AGENTS.md and NORTH_STAR. The promises become hard
   constraints in the plan and in the reviewer prompt.
2. **Plan template:** add a "Verification" section. For each step, it names
   the tests and checks that would fail if the step were wrong, and the new
   property, brute-force or regression tests it needs. Add a "Guardrail
   impact" section: any change to `verify` checks is listed as a human
   decision, because it can only produce NEEDS_HUMAN.
3. **Reviewer prompt:** add "does every step have a check that would fail if
   it were implemented wrong?" and "does any step weaken a promise or a
   check?"
4. **New Step 5, hand-off:** on SHIP, write `design-dir`, run `start-build`
   (unless `--gate`), print the draft PR link, and end.
5. Add evals: the Verification section exists; the hand-off calls the script;
   `--gate` stops after the draft PR.

### `/algo-build-loop`

1. **Verdict rules (the heart of the change):**
   - A commit needs a green `verify-fast` (the Stop and PostToolUse hooks
     back this up).
   - The end of a milestone needs gate **PASS at the milestone head SHA**
     before the reviewer is spawned.
   - A push needs a gate report for the SHA being pushed. Pushing FAIL is
     allowed, since the PR is a draft, but the body must say FAIL.
   - `gh pr ready` requires PASS (and `verify-deep` per D3) at the **PR head
     SHA**. A NEEDS_HUMAN branch stays a draft, with the reasons at the top.
   - Exit codes are authoritative. The agent never summarizes a verdict from
     memory. It pastes the report.
2. **Reviewer (Step 3):** the fresh subagent runs `verify` itself, in its own
   worktree at the given SHA, and must report the same verdict. A mismatch
   is a blocker, since it means a flake or an environment leak. It also gets
   the `guardrails` findings and is asked whether any test was weakened.
3. **Autonomous mode:** with `--autonomous`, pushing `feat/<slug>` and
   editing its PR are authorized by the hand-off. Merging never is, and it's
   denied in settings. The agent never asks questions. A design-level
   deviation goes into a "Blocked" section of the PR, and the build stops.
4. **Never bypass the judge:** no `--no-verify`, no editing guardrail files
   to get green, no retrying the gate until a flake passes. A gate that
   passes on its second run is reported as a flake finding.
5. **Step 4:** the PR body from `pr-body` is the main deliverable. The HTML
   artifact becomes optional and is linked from the PR.
6. Add evals: FAIL blocks `gh pr ready`; NEEDS_HUMAN stays a draft with
   reasons; the reviewer's verdict mismatch is logged as a blocker; a
   guardrail edit attempt is surfaced, not worked around.

Also bump both skills to `version: 0.2.0` and fix "algorec" in the
skills-algo README.

## Known risks

- **The workflow YAML comes from the PR branch** (see Step 20). This is
  acceptable while you are the only one merging. Switch to
  `pull_request_target` if outside PRs arrive.
- **Local and CI environments drift** (cache state, CPU speed, `$HOME`). A
  mismatch between the two verdicts is treated as a finding, never averaged
  away (Step 21).
- **Base-owned checks slow down legitimate guardrail improvements.** A branch
  that improves a check is judged by the old check and gets NEEDS_HUMAN.
  That's intended: guardrail changes get their own small PRs that you merge.
- **Subtle test weakening that no heuristic catches.** `--deep` mutation
  testing and the reviewer cover part of it. The NEEDS_HUMAN list and your
  merge cover the rest.
- **Local load causes flakes.** Parallel reviewer runs and the 2 s solver
  budget don't mix. Step 5 removes wall-clock sensitivity from the gate, and
  `--deep` re-runs expose what remains.
- **Headless context loss** in long builds. The build log plus the
  `SessionStart` hook are the recovery path. Test this in the dogfood run.
