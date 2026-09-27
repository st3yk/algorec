#!/usr/bin/env bash
set -uo pipefail

usage() {
  echo "usage: tools/agent/open_pr.sh <slug> [--base origin/master]" >&2
  exit 64
}

slug="${1:-}"
[[ -n "$slug" && "$slug" != -* ]] || usage
shift
base="origin/master"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)
      [[ $# -ge 2 && "$2" != -* ]] || usage
      base="$2"
      shift
      ;;
    *) usage ;;
  esac
  shift
done

repo="$(git rev-parse --show-toplevel)" || exit 3
cd "$repo" || exit 3
branch="$(git branch --show-current)"
if [[ "$branch" != feat/* ]]; then
  echo "open_pr: PRs come from feat/* branches (you are on '${branch:-a detached HEAD}')." >&2
  exit 64
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "open_pr: commit your changes first; the gate judges a commit." >&2
  exit 65
fi
git fetch --quiet origin || exit 3
if ! git cat-file -e "$base:tools/verify" 2>/dev/null; then
  echo "open_pr: $base has no tools/verify, so there is no trusted judge. A human opens this PR." >&2
  exit 3
fi

git show "$base:tools/verify" | bash -s -- --base "$base"
code=$?
sha="$(git rev-parse HEAD)"
report="$repo/.verify/reports/${sha:0:12}.json"
kind=""
if [[ -f "$report" ]]; then
  kind="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("human_kind", ""))' "$report")"
fi

label=""
case "$code" in
  0) ;;
  2)
    if [[ "$kind" != soft ]]; then
      echo "open_pr: NEEDS_HUMAN (${kind:-unknown}). The judge can't vouch for this change, so no PR is opened." >&2
      echo "open_pr: hand the branch to a human; the report is $report." >&2
      exit 2
    fi
    label="needs-human"
    ;;
  *)
    echo "open_pr: tools/verify exit $code. Fix the findings above; no PR is opened." >&2
    exit "$code"
    ;;
esac

STEERREC_OPEN_PR=1 git push --quiet -u origin "HEAD:refs/heads/$branch" || exit 3
body="$(mktemp)"
trap 'rm -f "$body"' EXIT
tools/pr_body "$slug" --base "$base" --report "$report" >"$body" || exit 3
title="$(sed -n 's/^# \(PR summary: \)\{0,1\}//p' "design/$slug/summary.md" 2>/dev/null | head -1)"
title="${title:-$branch}"
number="$(gh pr list --head "$branch" --state open --json number --jq '.[0].number // empty')" || exit 3
if [[ -n "$label" ]]; then
  gh label create "$label" --color FBCA04 --description "tools/verify: soft NEEDS_HUMAN" >/dev/null 2>&1 || true
fi
if [[ -z "$number" ]]; then
  args=(--head "$branch" --base "${base#origin/}" --title "$title" --body-file "$body")
  [[ -n "$label" ]] && args+=(--label "$label")
  gh pr create "${args[@]}" || exit 3
else
  gh pr edit "$number" --body-file "$body" || exit 3
  if [[ -n "$label" ]]; then
    gh pr edit "$number" --add-label "$label" || exit 3
  else
    gh pr edit "$number" --remove-label needs-human >/dev/null 2>&1 || true
  fi
  gh pr edit "$number" --remove-label not-ready >/dev/null 2>&1 || true
  gh pr ready "$number" >/dev/null 2>&1 || true
  echo "updated PR #$number"
fi
