#!/usr/bin/env bash
set -euo pipefail

apply=0
[[ "${1:-}" == "--apply" ]] && apply=1
repo="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
here="$(cd "$(dirname "$0")" && pwd)"
rules="$here/ruleset.json"
name="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["name"])' "$rules")"
existing="$(gh api "repos/$repo/rulesets" --jq ".[] | select(.name == \"$name\") | .id")"

if [[ "$apply" == 0 ]]; then
  echo "Would ${existing:+update ruleset $existing}${existing:-create a ruleset} on $repo:"
  cat "$rules"
  echo
  echo "Run with --apply to do it. Also turn on, in Settings > Code security:"
  echo "  secret scanning, push protection, and Dependabot alerts."
  exit 0
fi

if [[ -n "$existing" ]]; then
  gh api -X PUT "repos/$repo/rulesets/$existing" --input "$rules" --jq '"updated ruleset \(.id): \(.name)"'
else
  gh api -X POST "repos/$repo/rulesets" --input "$rules" --jq '"created ruleset \(.id): \(.name)"'
fi
