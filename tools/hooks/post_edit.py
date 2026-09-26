"""Claude Code PostToolUse hook: checks the file the agent just edited and reports problems
back to it at once (exit 2). See docs/guardrails.md."""

import json
import os
import sys

from tools.hooks.quick import check_files


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    path = (event.get("tool_input") or {}).get("file_path") or ""
    repo = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    rel = os.path.relpath(os.path.realpath(path), os.path.realpath(repo)) if path else ""
    if not rel or rel.startswith(".."):
        return 0
    problems = check_files(repo, [rel])
    if not problems:
        return 0
    print(f"{rel} breaks a repo check:\n" + "\n".join(problems), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
