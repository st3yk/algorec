"""Fails when a tracked file is invisible to the checks: not in //:repo_files, or a Python
file that lint or mypy never sees. See docs/guardrails.md."""

import fnmatch

from tools.verify_lib.findings import FAIL, Finding

REPO_FILES_EXEMPT = (".claude/*", ".github/*", ".gitignore", ".bazelignore", ".bazelversion", ".bazelrc")
MYPY_DIRS = ("steerrec/", "tools/")

INPUTS = {
    "repo": ("//:repo_files",),
    "lint": ("//:py_srcs", "//steerrec:py_srcs", "//tests:py_srcs", "//tools:py_srcs"),
    "mypy": ("//steerrec:py_srcs", "//tools:py_srcs"),
}


def source_paths(cquery_files: str) -> set[str]:
    out = set()
    for line in cquery_files.splitlines():
        line = line.strip()
        if line and not line.startswith(("bazel-out/", "external/", "/")):
            out.add(line)
    return out


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


def query_expression(targets: tuple[str, ...]) -> str:
    return f"set({' '.join(targets)})"
