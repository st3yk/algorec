"""Claude Code PostToolUse hook: checks the file the agent just edited and reports problems
back to it at once (exit 2). See docs/guardrails.md."""

import json
import os
import sys

from tools.hooks.quick import check_files, toplevel


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    path = (event.get("tool_input") or {}).get("file_path") or ""
    if not path:
        return 0
    path = os.path.join(event.get("cwd") or os.getcwd(), path)
    repo = toplevel(path)
    if repo is None:
        return 0
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(repo))
    if rel.startswith(".."):
        return 0
    problems = check_files(repo, [rel])
    if not problems:
        return 0
    print(f"{rel} breaks a repo check:\n" + "\n".join(problems), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
