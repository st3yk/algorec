"""Claude Code SessionStart hook: prints the branch, the working tree status and the
current state of any build log on this branch, for resumed sessions. See docs/guardrails.md."""

import glob
import json
import os
import re
import subprocess
import sys

from tools.hooks.quick import toplevel


def git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True).stdout.strip()


def current_state(text: str) -> str:
    m = re.search(r"^## Current state\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError, OSError):
        event = {}
    repo = toplevel(event.get("cwd") or os.getcwd()) or os.getcwd()
    branch = git(repo, "branch", "--show-current") or "(detached)"
    lines = [f"steerrec: branch {branch} at {git(repo, 'rev-parse', '--short', 'HEAD')}"]
    status = git(repo, "status", "--short")
    lines.append("working tree: clean" if not status else "working tree:\n" + status)
    for log in sorted(glob.glob(os.path.join(repo, "design", "*", "build-log.md"))):
        state = current_state(open(log, encoding="utf-8").read())
        if state:
            lines.append(f"{os.path.relpath(log, repo)} current state:\n{state}")
    lines.append("Before finishing, `tools/verify --fast` must pass; before pushing, run `tools/verify`.")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
