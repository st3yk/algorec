"""End-to-end tests of the tools/verify gate on scratch repositories, with a stub bazel on
PATH, so the entry script, the judge extraction and the exit codes are exercised for real.
See docs/guardrails.md."""

import json
import os
import shutil
import subprocess
import sys

import pytest

RUNFILES = os.path.join(os.environ.get("TEST_SRCDIR", ""), "_main")
JUDGE_FILES = [
    "tools/verify",
    "tools/__init__.py",
    "tools/proto_compat/__init__.py",
    "tools/proto_compat/listing.py",
]
ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}
FAKE_BAZEL = """#!/bin/sh
case "$1" in
  --version) echo "bazel stub" ;;
  cquery) git ls-files ;;
esac
exit 0
"""
TAMPERED_ENTRY = """#!/usr/bin/env bash
repo="$(git rev-parse --show-toplevel)"
PYTHONPATH="$repo" exec python3 -m tools.verify_lib.verify --repo "$repo" "$@"
"""


class Gate:
    def __init__(self, root: str):
        self.repo = os.path.join(root, "repo")
        self.env = {**os.environ, **ENV, "STEERREC_VERIFY_DIR": os.path.join(root, "cache")}
        bin_dir = os.path.join(root, "bin")
        os.makedirs(bin_dir)
        self._script(os.path.join(bin_dir, "bazel"), FAKE_BAZEL)
        self._script(os.path.join(bin_dir, "python3"), f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        self.env["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "master")
        for rel in JUDGE_FILES:
            self.copy(rel)
        for name in os.listdir(os.path.join(RUNFILES, "tools/verify_lib")):
            if name.endswith((".py", ".json")):
                self.copy(f"tools/verify_lib/{name}")
        self.write("README.md", "x\n")
        self.commit("chore: start")

    @staticmethod
    def _script(path: str, text: str) -> None:
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, 0o755)

    def copy(self, rel: str) -> None:
        dest = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy(os.path.join(RUNFILES, rel), dest)
        os.chmod(dest, 0o755 if rel == "tools/verify" else 0o644)

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", self.repo, *args], check=True, capture_output=True, text=True, env=self.env
        ).stdout

    def write(self, rel: str, text: str) -> None:
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        if rel == "tools/verify":
            os.chmod(path, 0o755)

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def verify(self, *args: str, entry: str | None = None) -> tuple[int, dict[str, object]]:
        if entry is None:
            command = [os.path.join(self.repo, "tools", "verify"), *args]
            result = subprocess.run(command, cwd=self.repo, capture_output=True, text=True, env=self.env)
        else:
            script = self.git("show", f"{entry}:tools/verify")
            command = ["bash", "-s", "--", *args]
            result = subprocess.run(command, cwd=self.repo, input=script, capture_output=True, text=True, env=self.env)
        sha = self.git("rev-parse", "--short=12", "HEAD").strip()
        path = os.path.join(self.repo, ".verify", "reports", f"{sha}.json")
        report: dict[str, object] = {}
        if os.path.exists(path):
            with open(path) as f:
                report = json.load(f)
        return result.returncode, report


@pytest.fixture
def gate(tmp_path):
    g = Gate(str(tmp_path))
    g.git("switch", "-q", "-c", "feat/x")
    return g


def finding_checks(report: dict[str, object]) -> set[str]:
    findings = report.get("findings", [])
    assert isinstance(findings, list)
    return {f["check"] for f in findings}


def test_a_clean_branch_passes_and_is_judged_by_the_merge_base(gate):
    gate.write("docs/note.md", "note\n")
    gate.commit("docs: add a note")
    code, report = gate.verify("--base", "master")
    assert code == 0 and report["verdict"] == "PASS"
    assert "matches the merge-base byte for byte" in str(report["judge"])


def test_uncommitted_changes_are_an_error(gate):
    gate.write("docs/note.md", "note\n")
    gate.commit("docs: add a note")
    gate.write("README.md", "changed\n")
    assert gate.verify("--base", "master")[0] == 3


def test_a_base_that_leaves_nothing_to_judge_is_an_error(gate):
    gate.write("docs/note.md", "note\n")
    gate.commit("docs: add a note")
    code, report = gate.verify("--base", "HEAD")
    assert code == 3 and "nothing to judge" in json.dumps(report)


def test_a_base_with_no_shared_history_is_an_error(gate):
    gate.git("switch", "-q", "--orphan", "other")
    gate.write("other.md", "x\n")
    gate.commit("docs: unrelated")
    gate.git("switch", "-q", "feat/x")
    gate.write("docs/note.md", "note\n")
    gate.commit("docs: add a note")
    assert gate.verify("--base", "other")[0] == 3


def test_a_loosened_commit_checker_is_still_judged_by_the_base(gate):
    path = os.path.join(gate.repo, "tools/verify_lib/commits.py")
    with open(path) as f:
        text = f.read()
    gate.write("tools/verify_lib/commits.py", text.replace("    out = []\n", "    return []\n    out = []\n", 1))
    gate.commit("update stuff")
    code, report = gate.verify("--base", "master")
    assert code == 1 and {"commits", "guardrails"} <= finding_checks(report)


def test_a_branch_entry_that_skips_the_base_judge_is_flagged(gate):
    gate.write("tools/verify", TAMPERED_ENTRY)
    gate.commit("refactor(verify): streamline the entry")
    code, report = gate.verify("--base", "master")
    assert code == 2 and "judge" in finding_checks(report)
    assert "this checkout's own" in str(report["judge"])


def test_the_base_entry_catches_a_branch_that_tampers_with_entry_and_judge(gate):
    path = os.path.join(gate.repo, "tools/verify_lib/verify.py")
    with open(path) as f:
        text = f.read()
    lying = text.replace("    return report.exit_code\n", "    return 0\n")
    assert lying != text
    gate.write("tools/verify_lib/verify.py", lying)
    gate.write("tools/verify", TAMPERED_ENTRY)
    gate.commit("refactor(verify): streamline the gate")
    assert gate.verify("--base", "master")[0] == 0
    code, report = gate.verify("--base", "master", entry="master")
    assert code == 2 and "guardrails" in finding_checks(report)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
