"""Claude Code PreToolUse hook for Bash: rejects `git push` forms that could reach the
default branch or rewrite history (exit 2). It is a speed bump, not a security boundary.
See docs/guardrails.md."""

import json
import re
import shlex
import sys

SEPARATORS = re.compile(r"&&|\|\||;|\||\n")
REJECTED_OPTIONS = ("--force", "-f", "--mirror", "--all", "--delete", "-d", "--prune", "--force-with-lease", "+")
ALLOWED_DESTINATION = re.compile(r"^(refs/heads/)?feat/[A-Za-z0-9._/-]+$")


def push_problems(command: str) -> list[str]:
    problems = []
    for part in SEPARATORS.split(command):
        try:
            words = shlex.split(part)
        except ValueError:
            continue
        while words and "=" in words[0] and not words[0].startswith("-"):
            words = words[1:]
        if len(words) < 2 or words[0] != "git":
            continue
        i = 1
        while i < len(words) and words[i].startswith("-"):
            i += 2 if words[i] in ("-C", "-c") else 1
        if i >= len(words) or words[i] != "push":
            continue
        args = words[i + 1 :]
        options = [a for a in args if a.startswith("-")]
        positional = [a for a in args if not a.startswith("-")]
        for option in options:
            if option.split("=", 1)[0] in REJECTED_OPTIONS or option.startswith("--force"):
                problems.append(f"`{option}` is not allowed")
        if len(positional) < 2:
            problems.append("name the remote and the feat/* branch explicitly: git push origin feat/<slug>")
            continue
        for spec in positional[1:]:
            if spec.startswith("+"):
                problems.append(f"`{spec}` is a force push")
                continue
            source, _, destination = spec.partition(":")
            if spec.startswith(":"):
                problems.append(f"`{spec}` deletes a remote branch")
            elif not ALLOWED_DESTINATION.match(destination or source):
                problems.append(f"`{spec}` pushes to `{destination or source}`; only feat/* branches are allowed")
    return problems


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    command = (event.get("tool_input") or {}).get("command") or ""
    problems = push_problems(command)
    if not problems:
        return 0
    print("git push blocked by tools/hooks/pre_bash.py:\n- " + "\n- ".join(problems), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
