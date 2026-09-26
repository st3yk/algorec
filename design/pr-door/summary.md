# PR summary: Open a PR only when the change is ready

## Summary

A PR now reaches GitHub only when `tools/verify` says the change is ready.

- **Soft and hard NEEDS_HUMAN.**
  - *Soft* means the change is probably fine and a human should look: an
    edited test, a new skip, a `Docs-Unchanged:` trailer.
  - *Hard* means the judge can't vouch for the change: a guardrail file
    changed, a `py_test` rule or `load()` line changed, the judge isn't the
    base's copy, or the tests fail under the base's guardrails.

  The report says which, as `human_kind`.
- **`tools/agent/open_pr.sh` is the only way agents reach GitHub.** It runs
  the base's gate. On PASS it pushes and opens (or updates and readies) a PR.
  On a soft NEEDS_HUMAN it does the same with a `needs-human` label. On
  anything else it pushes nothing.
- **Agents can't go around it.** The PreToolUse hook and
  `.claude/settings.json` reject direct `git push` and `gh pr
  create/ready/edit/merge/reopen`, and the `pre-push` git hook refuses
  pushes that didn't come through `open_pr.sh`. `start_build.sh` no longer
  opens a draft PR before any code exists.
- **GitHub enforces it too.** A gatekeeper workflow on `pull_request_target`
  runs the default branch's YAML, so a PR can't edit its own check, in two
  jobs:
  - a read-only job runs the base's judge and is the required `verify`
    check;
  - a write job that never touches PR code labels soft PRs and turns every
    PR that isn't ready back into a draft.

This branch also carries the fixes from PR #3 (the gaps left open by PR #2's
review): evidence tied to each test's `def`, any change to an existing
test's body flagged, skip handling, and the push-guard holes.

## Why

Before this change, the harness only stopped unproven changes from being
merged. Anything could still be pushed and opened as a PR, including this
branch's own predecessor, PR #3. The goal is stricter: a PR appears only
once the change is ready. Some rules are looser by design: a soft
NEEDS_HUMAN may open a ready PR for a human to review.

## Not done

- **This is a hard NEEDS_HUMAN change, so no agent PR.** It edits
  guardrail files, which by design only a human can accept. Review the
  branch and open the PR yourself.
- **The agent still holds your credentials and can write guardrail files
  through the shell.** A fine-grained token without pull-request
  permission, and a sandbox with the guardrail paths read-only, would turn
  these rules from speed bumps into boundaries. Both are your call.
- **The required-check context changes.** The `verify` check now comes from
  the `gatekeeper` workflow. It keeps the name `verify` and the GitHub
  Actions app, so the ruleset still matches it; check the first run after
  merging.
- **Mutation testing** and the **skill updates** are still follow-ups.
