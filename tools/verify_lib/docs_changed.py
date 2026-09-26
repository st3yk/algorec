"""Checks that a behavior change updates its docs page in the same commit, as AGENTS.md
requires. See docs/guardrails.md."""

import fnmatch
import json
import os

from tools.verify_lib.commits import commit_type
from tools.verify_lib.findings import FAIL, HUMAN, Finding
from tools.verify_lib.gitutil import Commit

BEHAVIOR_TYPES = ("feat", "fix", "perf", "revert")
TRAILER = "Docs-Unchanged"


def load_map(path: str | None = None) -> dict[str, list[str]]:
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs_map.json")
    with open(path, encoding="utf-8") as f:
        data: dict[str, list[str]] = json.load(f)
    return data


def docs_for(path: str, mapping: dict[str, list[str]]) -> list[str]:
    for pattern, docs in mapping.items():
        if path == pattern or fnmatch.fnmatchcase(path, pattern.replace("**", "*")):
            return docs
    return []


def check_docs(commits: list[Commit], mapping: dict[str, list[str]]) -> list[Finding]:
    out = []
    for c in commits:
        if commit_type(c.subject) not in BEHAVIOR_TYPES:
            continue
        missing: dict[str, list[str]] = {}
        for path in c.files:
            docs = docs_for(path, mapping)
            if docs and not set(docs) & set(c.files):
                missing[path] = docs
        if not missing:
            continue
        where = f"{c.short} {c.subject[:60]}"
        sources = ", ".join(sorted(missing))
        wanted = " or ".join(sorted({d for docs in missing.values() for d in docs}))
        reasons = c.trailers(TRAILER)
        if reasons:
            message = f"changes {sources} without {wanted}; the commit says why: {reasons[0]}"
            out.append(Finding("docs", HUMAN, message, where))
        else:
            out.append(
                Finding(
                    "docs",
                    FAIL,
                    f"changes {sources} but not {wanted}. Update the page in the same commit, "
                    f"or add a `{TRAILER}: <reason>` trailer for a human to accept",
                    where,
                )
            )
    return out
