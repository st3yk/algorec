#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: tools/agent/start_build.sh <slug> [--dry-run] [--gate] [--base origin/master]" >&2
  exit 64
}

slug="${1:-}"
[[ -n "$slug" && "$slug" != -* ]] || usage
shift
dry_run=0
gate=0
base="origin/master"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) dry_run=1 ;;
    --gate) gate=1 ;;
    --base) base="$2"; shift ;;
    *) usage ;;
  esac
  shift
done

[[ "$slug" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "slug must be lowercase letters, digits and dashes" >&2; exit 64; }
repo="$(git rev-parse --show-toplevel)"
design="$repo/design/$slug"
[[ -f "$design/plan.md" ]] || { echo "no plan at design/$slug/plan.md" >&2; exit 66; }
branch="feat/$slug"
wt="$repo/.claude/worktrees/$slug"
log_dir="${XDG_CACHE_HOME:-$HOME/.cache}/steerrec-agent"
title="$(sed -n 's/^# //p' "$design/plan.md" | head -1)"
title="${title:-$slug}"

run() {
  if [[ "$dry_run" == 1 ]]; then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

git -C "$repo" show-ref --verify --quiet "refs/heads/$branch" && { echo "branch $branch already exists" >&2; exit 73; }
[[ -e "$wt" ]] && { echo "worktree $wt already exists" >&2; exit 73; }

run git -C "$repo" fetch --quiet origin
run git -C "$repo" worktree add --quiet -b "$branch" "$wt" "$base"
run mkdir -p "$wt/design"
run cp -R "$design" "$wt/design/"
run git -C "$wt" add "design/$slug"
run git -C "$wt" commit --quiet -m "docs(design): add the $slug plan" -m "The vetted plan this branch implements."
run git -C "$wt" push --quiet -u origin "$branch"
if [[ "$dry_run" == 1 ]]; then
  run gh pr create --draft --head "$branch" --title "$title" --body-file "<tools/pr_body $slug>"
else
  body="$(mktemp)"
  (cd "$wt" && tools/pr_body "$slug" --base "$base") > "$body"
  (cd "$wt" && gh pr create --draft --head "$branch" --title "$title" --body-file "$body")
  rm -f "$body"
fi

if [[ "$gate" == 1 ]]; then
  echo "--gate: stopping after the plan-only draft PR. Start the build with:"
  echo "  (cd $wt && claude -p '/algo-build-loop design/$slug/plan.md --autonomous')"
  exit 0
fi

run mkdir -p "$log_dir"
prompt="/algo-build-loop design/$slug/plan.md --autonomous"
if [[ "$dry_run" == 1 ]]; then
  run claude -p "$prompt" --permission-mode acceptEdits --output-format stream-json --verbose
  echo "(in $wt, in the background, logging to $log_dir/$slug.log)"
else
  (cd "$wt" && nohup claude -p "$prompt" --permission-mode acceptEdits --output-format stream-json --verbose \
    > "$log_dir/$slug.log" 2>&1 &)
  echo "build started in $wt; log: $log_dir/$slug.log"
fi
