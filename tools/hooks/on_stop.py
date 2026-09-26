"""Claude Code Stop hook: an agent can't finish while `tools/verify --fast` fails on a
working tree it changed (exit 2 sends it back). See docs/guardrails.md."""

import hashlib
import json
import os
import subprocess
import sys

STAMP = os.path.join(".verify", "last-fast-green")
MAX_REPORT_LINES = 40


def fingerprint(repo: str) -> str:
    h = hashlib.sha256()
    for args in (["rev-parse", "HEAD"], ["diff", "HEAD", "--binary"], ["ls-files", "--others", "--exclude-standard"]):
        h.update(subprocess.run(["git", "-C", repo, *args], capture_output=True).stdout)
    others = subprocess.run(
        ["git", "-C", repo, "ls-files", "--others", "--exclude-standard", "-z"], capture_output=True
    ).stdout.split(b"\0")
    for name in filter(None, others):
        try:
            with open(os.path.join(repo, name.decode()), "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())
        except OSError:
            continue
    return h.hexdigest()


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        event = {}
    if event.get("stop_hook_active"):
        return 0
    repo = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    stamp = os.path.join(repo, STAMP)
    current = fingerprint(repo)
    try:
        with open(stamp, encoding="utf-8") as f:
            if f.read().strip() == current:
                return 0
    except OSError:
        pass
    result = subprocess.run([os.path.join(repo, "tools", "verify"), "--fast"], cwd=repo, capture_output=True, text=True)
    if result.returncode == 0:
        os.makedirs(os.path.dirname(stamp), exist_ok=True)
        with open(stamp, "w", encoding="utf-8") as f:
            f.write(current)
        return 0
    lines = (result.stdout + result.stderr).strip().splitlines()
    print("tools/verify --fast fails on your changes; fix them before finishing:", file=sys.stderr)
    print("\n".join(lines[:MAX_REPORT_LINES]), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
