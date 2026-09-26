#!/usr/bin/env bash
set -euo pipefail
repo="$(git rev-parse --show-toplevel)"
git -C "$repo" config core.hooksPath tools/githooks
echo "git hooks enabled: commit-msg, pre-commit and pre-push run from tools/githooks/"
