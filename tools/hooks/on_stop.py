"""Claude Code Stop hook: an agent can't finish while `tools/verify --fast` fails on a
working tree it changed (exit 2 sends it back). See docs/guardrails.md."""

import hashlib
import json
import os
import subprocess
import sys

from tools.hooks.quick import toplevel

STAMP = os.path.join(".verify", "last-fast-green")
RED = os.path.join(".verify", "last-fast-red")
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
    repo = toplevel(event.get("cwd") or os.getcwd())
    if repo is None or not os.path.exists(os.path.join(repo, "tools", "verify")):
        return 0
    stamp, red = os.path.join(repo, STAMP), os.path.join(repo, RED)
    current = fingerprint(repo)
    if read(stamp) == current:
        return 0
    cached = read(red)
    if cached.startswith(current + "\n"):
        return block(cached.split("\n", 1)[1])
    result = subprocess.run([os.path.join(repo, "tools", "verify"), "--fast"], cwd=repo, capture_output=True, text=True)
    os.makedirs(os.path.dirname(stamp), exist_ok=True)
    if result.returncode == 0:
        with open(stamp, "w", encoding="utf-8") as f:
            f.write(current)
        return 0
    report = "\n".join((result.stdout + result.stderr).strip().splitlines()[:MAX_REPORT_LINES])
    with open(red, "w", encoding="utf-8") as f:
        f.write(current + "\n" + report)
    return block(report)


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def block(report: str) -> int:
    print("tools/verify --fast fails on your changes; fix them before finishing:", file=sys.stderr)
    print(report, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
