"""Checks every commit on the branch against the commit conventions in AGENTS.md.
See docs/guardrails.md."""

import re

from tools.verify_lib.findings import FAIL, Finding
from tools.verify_lib.gitutil import Commit

TYPES = ("feat", "fix", "test", "refactor", "build", "chore", "docs", "perf", "style", "ci", "revert")
SUBJECT = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[a-z0-9][a-z0-9_-]*)\))?(?P<bang>!)?: (?P<summary>\S.*)$")
MAX_SUBJECT = 72
FORBIDDEN_PREFIXES = ("wip", "fixup!", "squash!", "amend!")
GIT_REVERT = re.compile(r'^Revert "[a-z]+(\([a-z0-9][a-z0-9_-]*\))?!?: \S.*"$')
LOCK_ONLY = {"requirements.in", "requirements_lock.txt", "MODULE.bazel", "MODULE.bazel.lock"}
LOCK_FILES = {"requirements_lock.txt", "MODULE.bazel.lock"}


def commit_type(subject: str) -> str | None:
    m = SUBJECT.match(subject)
    return m.group("type") if m else None


def check_commits(commits: list[Commit]) -> list[Finding]:
    out = []
    for c in commits:
        where = f"{c.short} {c.subject[:60]}"
        if c.parents > 1:
            out.append(
                Finding("commits", FAIL, "merge commits aren't allowed on a feature branch; rebase instead", where)
            )
            continue
        if c.subject.lower().startswith(FORBIDDEN_PREFIXES):
            out.append(
                Finding("commits", FAIL, "work-in-progress or fixup commit; squash it into a real commit", where)
            )
            continue
        m = SUBJECT.match(c.subject)
        if GIT_REVERT.match(c.subject):
            pass
        elif not m or m.group("type") not in TYPES:
            out.append(
                Finding(
                    "commits",
                    FAIL,
                    f"subject isn't a Conventional Commit `type(scope): summary` with type in {', '.join(TYPES)}",
                    where,
                )
            )
        elif m.group("summary")[0].isupper() and not m.group("summary")[:2].isupper():
            out.append(
                Finding("commits", FAIL, "summary starts with a capital letter; use the imperative, lowercase", where)
            )
        if len(c.subject) > MAX_SUBJECT:
            out.append(
                Finding("commits", FAIL, f"subject is {len(c.subject)} characters; the limit is {MAX_SUBJECT}", where)
            )
        touched = set(c.files)
        if touched & LOCK_FILES and not touched <= LOCK_ONLY:
            extra = ", ".join(sorted(touched - LOCK_ONLY)[:3])
            out.append(
                Finding("commits", FAIL, f"lock-file changes must be their own commit (also touches {extra})", where)
            )
    return out
