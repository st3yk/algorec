"""Claude Code PreToolUse hook for Bash: rejects `git push` forms that could reach the
default branch or rewrite history (exit 2). It is a speed bump, not a security boundary.
See docs/guardrails.md."""

import json
import os
import re
import shlex
import sys

SEPARATORS = re.compile(r"&&|\|\||;|\||\n")
REJECTED_OPTIONS = ("--force", "--mirror", "--all", "--delete", "--prune", "--force-with-lease", "--force-if-includes")
REJECTED_SHORT = ("f", "d")
VALUE_OPTIONS = ("-o", "--push-option", "--repo", "--receive-pack", "--exec")
GIT_VALUE_OPTIONS = ("-C", "-c", "--git-dir", "--work-tree", "--namespace")
WRAPPERS = ("command", "exec", "nohup", "time", "sudo", "builtin")
SHELLS = ("bash", "sh", "zsh", "dash")
REDIRECTION = re.compile(r"^\d*(>>?|<)(&\d+)?")
ALLOWED_DESTINATION = re.compile(r"^(refs/heads/)?feat/[A-Za-z0-9._/-]+$")


def _strip_prefix(words: list[str]) -> list[str]:
    while words:
        head = os.path.basename(words[0])
        if "=" in words[0] and not words[0].startswith("-"):
            words = words[1:]
        elif head == "env":
            words = words[1:]
            while words and (words[0].startswith("-") or ("=" in words[0])):
                words = words[1:]
        elif head in WRAPPERS:
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[1:]
        else:
            break
    return words


def _pushes(command: str, depth: int = 0) -> list[list[str]]:
    out = []
    for part in SEPARATORS.split(command):
        try:
            words = _strip_prefix(shlex.split(part))
        except ValueError:
            continue
        if not words:
            continue
        program = os.path.basename(words[0])
        if program in SHELLS and "-c" in words and depth < 3:
            script = words[words.index("-c") + 1] if words.index("-c") + 1 < len(words) else ""
            out += _pushes(script, depth + 1)
            continue
        if program != "git":
            continue
        i = 1
        while i < len(words) and words[i].startswith("-"):
            i += 2 if words[i] in GIT_VALUE_OPTIONS else 1
        if i < len(words) and words[i] == "push":
            out.append(words[i + 1 :])
    return out


def _problems(args: list[str]) -> list[str]:
    problems = []
    positional = []
    i = 0
    while i < len(args):
        arg = args[i]
        if REDIRECTION.match(arg):
            i += 2 if arg in (">", ">>", "<", "2>") else 1
            continue
        if arg in VALUE_OPTIONS:
            i += 2
            continue
        if arg.startswith("--"):
            if arg.split("=", 1)[0] in REJECTED_OPTIONS or arg.startswith("--force"):
                problems.append(f"`{arg}` is not allowed")
        elif arg.startswith("-") and len(arg) > 1:
            flags = arg[1:]
            if "o" in flags:
                i += 2
                continue
            for flag in flags:
                if flag in REJECTED_SHORT:
                    problems.append(f"`-{flag}` (in `{arg}`) is not allowed")
        else:
            positional.append(arg)
        i += 1
    if len(positional) < 2:
        problems.append("name the remote and the feat/* branch explicitly: git push origin feat/<slug>")
        return problems
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


def push_problems(command: str) -> list[str]:
    problems = []
    for args in _pushes(command):
        problems += _problems(args)
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
