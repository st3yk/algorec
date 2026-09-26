<!-- Agents: generate this body with `tools/pr_body <slug>` instead of filling it by hand. -->

**`tools/verify` verdict:** <!-- paste the first line of .verify/reports/<sha>.md -->

## Summary

## Why

## Commits

## Verification

<!-- The full gate report for the PR head: `.verify/reports/<sha>.md`. -->

## Review rounds

## Deviations from the plan

## Not done

## How to check it yourself

```sh
git fetch origin && git checkout <sha>
tools/verify --base origin/master
```
