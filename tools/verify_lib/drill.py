"""The guardrail drill: plants one known fault per branch in a scratch clone and checks that
tools/verify gives the expected verdict, and that the earliest hook catches it.
See docs/guardrails.md."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass

EXIT = {0: "PASS", 1: "FAIL", 2: "NEEDS_HUMAN", 3: "ERROR"}
ENV = {
    "GIT_AUTHOR_NAME": "drill",
    "GIT_AUTHOR_EMAIL": "drill@example.com",
    "GIT_COMMITTER_NAME": "drill",
    "GIT_COMMITTER_EMAIL": "drill@example.com",
}

Edit = Callable[[str], None]


@dataclass
class Fault:
    name: str
    edit: Edit
    message: str | None
    verdict: str
    hook: str = ""
    hook_file: str = ""

    @property
    def hook_rejects(self) -> int:
        return 2 if self.hook == "post_edit" else 1


def replace(rel: str, old: str, new: str) -> Edit:
    def edit(clone: str) -> None:
        path = os.path.join(clone, rel)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if text.count(old) != 1:
            raise RuntimeError(f"drill edit doesn't apply to {rel}: {old[:60]!r}")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace(old, new))

    return edit


def write(rel: str, text: str, mode: int = 0o644) -> Edit:
    def edit(clone: str) -> None:
        path = os.path.join(clone, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, mode)

    return edit


def both(*edits: Edit) -> Edit:
    def edit(clone: str) -> None:
        for e in edits:
            e(clone)

    return edit


def touch_doc(rel: str) -> Edit:
    def edit(clone: str) -> None:
        with open(os.path.join(clone, rel), "a", encoding="utf-8") as f:
            f.write("\nA drill note.\n")

    return edit


def lock_hash(clone: str) -> None:
    path = os.path.join(clone, "requirements_lock.txt")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"--hash=sha256:([0-9a-f])", text)
    if not m:
        raise RuntimeError("no hash in requirements_lock.txt")
    flipped = "0" if m.group(1) != "0" else "1"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text[: m.start(1)] + flipped + text[m.end(1) :])


TEST_FOOTER = 'if __name__ == "__main__":\n    raise SystemExit(pytest.main([__file__, "-q"]))\n'
NEUTRAL_ROWS_REMOVED = both(
    replace(
        "steerrec/assembler.py",
        "            add(row, b.reference * page_size - SLACK_TOL, np.inf)\n",
        "            pass\n",
    ),
    replace(
        "steerrec/assembler.py",
        "            add(row, -np.inf, b.reference * page_size + SLACK_TOL)\n",
        "            pass\n",
    ),
    touch_doc("docs/code/assembler.md"),
)
FAKE_BAZEL_WRAPPER = """#!/usr/bin/env bash
if [[ "${1:-}" == test ]]; then
  exit 0
fi
exec "$BAZEL_REAL" "$@"
"""

FAULTS = [
    Fault("control: a docs-only change", touch_doc("docs/concepts.md"), "docs: add a drill note", "PASS"),
    Fault(
        "inline comment in steerrec/",
        replace(
            "steerrec/items.py", "from types import MappingProxyType\n", "from types import MappingProxyType  # why\n"
        ),
        "refactor(items): explain an import",
        "FAIL",
        "post_edit",
        "steerrec/items.py",
    ),
    Fault(
        "function docstring",
        replace(
            "steerrec/registry.py",
            "def single_slider(s: float) -> dict[str, float]:\n",
            'def single_slider(s: float) -> dict[str, float]:\n    """Map the slider."""\n',
        ),
        "refactor(registry): document single_slider",
        "FAIL",
        "post_edit",
        "steerrec/registry.py",
    ),
    Fault(
        "test file without a py_test rule",
        write("tests/test_extra.py", "import pytest\n\n\ndef test_extra():\n    assert True\n\n\n" + TEST_FOOTER),
        "test: add an extra test",
        "FAIL",
    ),
    Fault(
        "behavior change without its docs page",
        replace(
            "steerrec/targets.py",
            "\ndef compute_bounds(",
            "\ndef drill_helper() -> int:\n    return 1\n\n\ndef compute_bounds(",
        ),
        "feat(targets): add a helper",
        "FAIL",
    ),
    Fault(
        "the same, with a Docs-Unchanged trailer",
        replace(
            "steerrec/targets.py",
            "\ndef compute_bounds(",
            "\ndef drill_helper() -> int:\n    return 1\n\n\ndef compute_bounds(",
        ),
        "feat(targets): add a helper\n\nDocs-Unchanged: internal helper, nothing user-visible",
        "NEEDS_HUMAN",
    ),
    Fault(
        "proto field renumbered",
        replace("proto/steerrec/v1/recommender.proto", "  uint32 batch_size = 3;", "  uint32 batch_size = 9;"),
        "refactor(proto): renumber batch_size",
        "FAIL",
    ),
    Fault(
        "assembler serves a page below neutral", NEUTRAL_ROWS_REMOVED, "fix(assembler): drop the neutral rows", "FAIL"
    ),
    Fault(
        "tests disabled by an early exit above the footer",
        replace(
            "tests/test_targets.py",
            TEST_FOOTER,
            'if __name__ == "__main__":\n    raise SystemExit(0)\n\n\n' + TEST_FOOTER,
        ),
        "test(targets): tidy the entry point",
        "FAIL",
    ),
    Fault(
        "tests skipped through an alias",
        both(
            replace(
                "tests/test_model.py",
                "\n\ndef test_item_rejects_non_probabilities",
                "\n\n_off = pytest.mark.skip\n\n\n@_off\ndef test_item_rejects_non_probabilities",
            ),
        ),
        "test(model): park a test",
        "FAIL",
    ),
    Fault(
        "a tools/bazel wrapper that fakes a passing test run",
        both(write("tools/bazel", FAKE_BAZEL_WRAPPER, 0o755), NEUTRAL_ROWS_REMOVED),
        "build: add a bazel wrapper",
        "FAIL",
    ),
    Fault(
        "shortfall silently dropped",
        both(
            replace(
                "steerrec/assembler.py",
                "    out = []\n    for b in bounds:\n        gap = _gap(b, items)",
                "    return []\n    out = []\n    for b in bounds:\n        gap = _gap(b, items)",
            ),
            touch_doc("docs/code/assembler.md"),
        ),
        "fix(assembler): stop reporting shortfall",
        "FAIL",
    ),
    Fault("hand-edited lock file", lock_hash, "build: bump a hash", "FAIL"),
    Fault(
        "deleted assertion",
        replace(
            "tests/test_targets.py",
            "    assert exclusive_mass(it, EDUCATIONAL, pushed_up=(EDUCATIONAL,)) == pytest.approx(0.7)\n",
            "",
        ),
        "test(targets): trim a check",
        "NEEDS_HUMAN",
    ),
    Fault(
        "commit checker loosened on the branch",
        replace(
            "tools/verify_lib/commits.py",
            "def check_commits(commits: list[Commit]) -> list[Finding]:\n",
            "def check_commits(commits: list[Commit]) -> list[Finding]:\n    return []\n",
        ),
        "update stuff",
        "FAIL",
    ),
    Fault("non-conventional commit subject", touch_doc("docs/concepts.md"), "update stuff", "FAIL", "commit_msg"),
    Fault(
        "CI workflow edited",
        replace(".github/workflows/verify.yml", "    timeout-minutes: 30\n", "    timeout-minutes: 5\n"),
        "ci: shorten the timeout",
        "NEEDS_HUMAN",
    ),
    Fault(
        "new package no check sees",
        both(
            write("steerrec/serving/BUILD.bazel", 'filegroup(\n    name = "x",\n    srcs = ["foo.py"],\n)\n'),
            write("steerrec/serving/foo.py", '"""Serving. See docs/README.md."""\n\nX = 1\n'),
        ),
        "build(serving): add a package",
        "FAIL",
    ),
    Fault("uncommitted change", touch_doc("docs/concepts.md"), None, "ERROR"),
]


def git(clone: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", clone, "-c", "core.hooksPath=/dev/null", *args],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **ENV},
    ).stdout


def run_hook(clone: str, fault: Fault) -> int | None:
    if not fault.hook:
        return None
    runner = os.path.join(clone, "tools", "hooks", "run")
    env = {**os.environ, "CLAUDE_PROJECT_DIR": clone}
    if fault.hook == "post_edit":
        event = json.dumps({"tool_input": {"file_path": os.path.join(clone, fault.hook_file)}})
        return subprocess.run([runner, "post_edit"], input=event, text=True, capture_output=True, env=env).returncode
    message = os.path.join(clone, ".git", "DRILL_MSG")
    with open(message, "w", encoding="utf-8") as f:
        f.write((fault.message or "") + "\n")
    return subprocess.run([runner, "commit_msg", message], cwd=clone, capture_output=True, env=env).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/verify_drill", description=__doc__)
    parser.add_argument("--only", help="run only faults whose name contains this text")
    parser.add_argument("--keep", action="store_true", help="keep the scratch clone")
    args = parser.parse_args(argv)
    repo = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
    source = repo.stdout.strip()
    head = subprocess.run(["git", "-C", source, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    work = tempfile.mkdtemp(prefix="verify-drill-")
    clone = os.path.join(work, "clone")
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", source, clone], check=True)
    git(clone, "switch", "--quiet", "-C", "drill-base", head)
    env = {**os.environ, **ENV, "STEERREC_VERIFY_DIR": os.path.join(work, "verify-cache")}
    faults = [f for f in FAULTS if not args.only or args.only in f.name]
    print(f"drill: {len(faults)} fault(s) against {head[:12]} in {clone}")
    failures = 0
    for i, fault in enumerate(faults):
        git(clone, "switch", "--quiet", "--force", "-C", f"drill-{i}", "drill-base")
        git(clone, "clean", "-fdq")
        fault.edit(clone)
        hook_code = run_hook(clone, fault)
        if fault.message is not None:
            git(clone, "add", "-A")
            git(clone, "commit", "--quiet", "-m", fault.message)
        start = time.monotonic()
        result = subprocess.run(
            [os.path.join(clone, "tools", "verify"), "--base", "drill-base"], cwd=clone, capture_output=True, env=env
        )
        verdict = EXIT.get(result.returncode, f"exit {result.returncode}")
        ok = verdict == fault.verdict and (hook_code is None or hook_code == fault.hook_rejects)
        failures += not ok
        hook = "" if hook_code is None else f" hook {fault.hook}: exit {hook_code}"
        mark = "ok  " if ok else "MISS"
        print(
            f"{mark} {fault.name:<42} expected {fault.verdict:<11} got {verdict:<11}{hook} ({time.monotonic() - start:.0f}s)"
        )
        if not ok:
            print("\n".join(result.stdout.decode(errors="replace").splitlines()[:25]))
        git(clone, "reset", "--quiet", "--hard")
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    print(f"drill: {len(faults) - failures}/{len(faults)} as expected")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
