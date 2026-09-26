"""Fails when a tracked file is invisible to the checks: not in //:repo_files, or a Python
file that lint or mypy never sees. See docs/guardrails.md."""

import fnmatch

from tools.verify_lib.findings import FAIL, Finding

REPO_FILES_EXEMPT = (".claude/*", ".github/*", ".gitignore", ".bazelignore", ".bazelversion", ".bazelrc")
MYPY_DIRS = ("steerrec/", "tools/")

TARGETS = {
    "repo": "//:repo_files",
    "lint": "//tools/lint:ruff_check",
    "mypy": "//tools/lint:mypy",
}


def label_to_path(label: str) -> str | None:
    if not label.startswith("//"):
        return None
    package, _, name = label[2:].partition(":")
    return f"{package}/{name}" if package else name


def check_coverage(tracked: list[str], seen: dict[str, set[str]]) -> list[Finding]:
    out = []
    for path in sorted(tracked):
        if not any(fnmatch.fnmatchcase(path, p) for p in REPO_FILES_EXEMPT) and path not in seen["repo"]:
            out.append(
                Finding(
                    "coverage",
                    FAIL,
                    "no check sees this file. Add its package's `all_files` filegroup to //:repo_files",
                    path,
                )
            )
        if not path.endswith(".py"):
            continue
        if path not in seen["lint"]:
            out.append(
                Finding(
                    "coverage", FAIL, "ruff never lints this file. Add its package's `py_srcs` to the lint set", path
                )
            )
        if path.startswith(MYPY_DIRS) and path not in seen["mypy"]:
            out.append(
                Finding(
                    "coverage",
                    FAIL,
                    "mypy never checks this file. Add its package's `py_srcs` to //tools/lint:mypy",
                    path,
                )
            )
    return out


def query_expression(target: str) -> str:
    return f'kind("source file", deps({target}))'
