"""Claude Code PreToolUse hook for Bash: agents don't push or open PRs themselves. That goes
through tools/agent/open_pr.sh, which checks the verdict first (exit 2 sends the agent
there). It is a speed bump, not a security boundary. See docs/guardrails.md."""

import json
import os
import re
import shlex
import sys

SEPARATORS = re.compile(r"&&|\|\||;|\||\n")
GIT_VALUE_OPTIONS = ("-C", "-c", "--git-dir", "--work-tree", "--namespace")
WRAPPERS = ("command", "exec", "nohup", "time", "sudo", "builtin")
SHELLS = ("bash", "sh", "zsh", "dash")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1")
GH_PR_BLOCKED = ("create", "ready", "edit", "merge", "reopen")
DOOR = "tools/agent/open_pr.sh <slug>"


def strip_heredocs(command: str) -> str:
    out = []
    delimiter: str | None = None
    for line in command.split("\n"):
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        out.append(line)
        m = HEREDOC.search(line)
        if m:
            delimiter = m.group(2)
    return "\n".join(out)


def _strip_prefix(words: list[str]) -> list[str]:
    while words:
        head = os.path.basename(words[0])
        if "=" in words[0] and not words[0].startswith("-"):
            words = words[1:]
        elif head == "env":
            words = words[1:]
            while words and (words[0].startswith("-") or "=" in words[0]):
                words = words[1:]
        elif head in WRAPPERS:
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[1:]
        else:
            break
    return words


def commands(command: str, depth: int = 0) -> list[list[str]]:
    out = []
    for part in SEPARATORS.split(strip_heredocs(command)):
        try:
            words = _strip_prefix(shlex.split(part))
        except ValueError:
            continue
        if not words:
            continue
        program = os.path.basename(words[0])
        if program in SHELLS and "-c" in words and depth < 3:
            i = words.index("-c") + 1
            out += commands(words[i] if i < len(words) else "", depth + 1)
            continue
        out.append([program, *words[1:]])
    return out


def problems(command: str) -> list[str]:
    out = []
    for words in commands(command):
        program, args = words[0], words[1:]
        if program == "git":
            i = 0
            while i < len(args) and args[i].startswith("-"):
                i += 2 if args[i] in GIT_VALUE_OPTIONS else 1
            if i < len(args) and args[i] == "push":
                out.append(f"`git push` is not for agents; {DOOR} pushes once the change is ready")
        elif program == "gh" and len(args) >= 2 and args[0] == "pr" and args[1] in GH_PR_BLOCKED:
            out.append(f"`gh pr {args[1]}` is not for agents; {DOOR} opens or updates the PR once it's ready")
    return out


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    command = (event.get("tool_input") or {}).get("command") or ""
    found = problems(command)
    if not found:
        return 0
    print("blocked by tools/hooks/pre_bash.py:\n- " + "\n- ".join(found), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
