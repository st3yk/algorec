"""Per-file checks fast enough to run after every edit: ruff and the convention rules.
See docs/guardrails.md."""

import glob
import os
import subprocess

from tools.conventions.conventions import check_python

RUFF_CACHE = os.path.join(".verify", "ruff-path")
BAZEL_INFO_TIMEOUT_S = 5


def toplevel(path: str) -> str | None:
    start = path if os.path.isdir(path) else os.path.dirname(path) or "."
    while not os.path.isdir(start):
        start = os.path.dirname(start)
    result = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def ruff_bin(repo: str) -> str | None:
    cached = os.path.join(repo, RUFF_CACHE)
    try:
        with open(cached, encoding="utf-8") as f:
            path = f.read().strip()
        if os.access(path, os.X_OK):
            return path
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["bazel", "info", "output_base"], cwd=repo, capture_output=True, text=True, timeout=BAZEL_INFO_TIMEOUT_S
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    matches = sorted(glob.glob(os.path.join(result.stdout.strip(), "external", "*pypi*ruff*", "bin", "ruff")))
    if not matches:
        return None
    os.makedirs(os.path.dirname(cached), exist_ok=True)
    with open(cached, "w", encoding="utf-8") as f:
        f.write(matches[-1])
    return matches[-1]


def check_files(repo: str, paths: list[str]) -> list[str]:
    py = [p for p in paths if p.endswith(".py") and os.path.exists(os.path.join(repo, p))]
    if not py:
        return []
    problems = []
    for path in py:
        with open(os.path.join(repo, path), encoding="utf-8") as f:
            text = f.read()
        problems += [v.render() for v in check_python(path, text, lambda ref: os.path.exists(os.path.join(repo, ref)))]
    ruff = ruff_bin(repo)
    if ruff is None:
        return problems
    lint = subprocess.run([ruff, "check", "--quiet", *py], cwd=repo, capture_output=True, text=True)
    if lint.returncode:
        problems.append((lint.stdout + lint.stderr).strip())
    fmt = subprocess.run([ruff, "format", "--check", "--quiet", *py], cwd=repo, capture_output=True, text=True)
    if fmt.returncode:
        files = ", ".join(line.split(":", 1)[-1].strip() for line in (fmt.stdout + fmt.stderr).splitlines() if line)
        problems.append(f"not formatted: {files}. Fix with: bazel run //tools/lint:fix")
    return problems
