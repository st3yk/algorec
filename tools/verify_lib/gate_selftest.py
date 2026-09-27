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
  test)
    if [ -n "$FAKE_TEST_XML" ]; then
      mkdir -p "$FAKE_TESTLOGS/t"
      cp "$FAKE_TEST_XML" "$FAKE_TESTLOGS/t/test.xml"
      ln -sfn "$FAKE_TESTLOGS" bazel-testlogs
    fi
    ;;
esac
exit 0
"""
TEST_FILE = "def test_one():\n    assert True\n\n\ndef test_two():\n    assert True\n"


def junit(*cases: str) -> str:
    body = "".join(cases)
    return f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{body}</testsuite></testsuites>'


LINES = {"test_one": 1, "test_two": 5}


def case(name: str, child: str = "", where: str | None = None) -> str:
    line = LINES[name.split("[")[0]]
    at = f"tests/test_x.py:{line}" if where is None else where
    props = f'<properties><property name="defined_at" value="{at}" /></properties>' if at else ""
    return f'<testcase classname="tests.test_x" name="{name}">{props}{child}</testcase>'


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
        self.env["FAKE_TESTLOGS"] = os.path.join(root, "testlogs")
        self.xml = os.path.join(root, "test.xml")
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "master")
        for rel in JUDGE_FILES:
            self.copy(rel)
        for name in os.listdir(os.path.join(RUNFILES, "tools/verify_lib")):
            if name.endswith((".py", ".json")) and not name.endswith("_selftest.py"):
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


def test_every_test_function_needs_a_passed_result(gate):
    gate.write("tests/test_x.py", TEST_FILE)
    gate.commit("test: add tests")
    with open(gate.xml, "w") as f:
        f.write(junit(case("test_one"), case("test_two[1]"), case("test_two[2]")))
    gate.env["FAKE_TEST_XML"] = gate.xml
    assert gate.verify("--base", "master")[0] == 0


@pytest.mark.parametrize(
    "cases, fragment",
    [
        ((), "`test_one` never ran"),
        ((case("test_one"),), "`test_two` never ran"),
        ((case("test_one"), case("test_two", "<failure/>")), "`test_two` ran but never passed (failure)"),
        ((case("test_one"), case("test_two", where="")), "`test_two` ran without a definition record"),
        ((case("test_one"), case("test_two", where="tests/test_x.py:9")), "came from tests/test_x.py:9"),
    ],
)
def test_missing_substituted_or_failed_results_fail(gate, cases, fragment):
    gate.write("tests/test_x.py", TEST_FILE)
    gate.commit("test: add tests")
    with open(gate.xml, "w") as f:
        f.write(junit(*cases))
    gate.env["FAKE_TEST_XML"] = gate.xml
    code, report = gate.verify("--base", "master")
    assert code == 1 and fragment in json.dumps(report)


def test_a_test_rebound_to_a_lambda_fails_evidence(gate):
    gate.write("tests/test_x.py", TEST_FILE + '\nglobals()["test_two"] = lambda: None\n')
    gate.commit("test: add tests")
    with open(gate.xml, "w") as f:
        f.write(junit(case("test_one"), case("test_two", where="tests/test_x.py:8")))
    gate.env["FAKE_TEST_XML"] = gate.xml
    code, report = gate.verify("--base", "master")
    assert code == 1 and "came from tests/test_x.py:8, not the def at tests/test_x.py:5" in json.dumps(report)


def test_a_new_skip_asks_a_human_and_a_skip_from_the_base_is_accepted(gate):
    gate.write("tests/test_x.py", TEST_FILE)
    gate.commit("test: add tests")
    with open(gate.xml, "w") as f:
        f.write(junit(case("test_one"), case("test_two", "<skipped/>")))
    gate.env["FAKE_TEST_XML"] = gate.xml
    code, report = gate.verify("--base", "master")
    assert code == 2 and "`test_two` is newly skipped" in json.dumps(report)
    gate.git("switch", "-q", "master")
    gate.write("tests/test_x.py", TEST_FILE.replace("def test_two", "@skip\ndef test_two"))
    gate.commit("test: skip test_two")
    gate.git("switch", "-q", "-c", "feat/y")
    gate.write("docs/y.md", "y\n")
    gate.commit("docs: add y")
    with open(gate.xml, "w") as f:
        f.write(junit(case("test_one"), case("test_two", "<skipped/>", where="tests/test_x.py:5")))
    code, report = gate.verify("--base", "master")
    assert code == 0, json.dumps(report)


def test_post_merge_skips_review_time_checks_but_still_judges_the_tree(gate):
    gate.write("tools/verify_lib/extra.py", "X = 1\n")
    gate.commit("Merge pull request #9 from someone/branch")
    assert gate.verify("--base", "master")[0] != 0
    code, report = gate.verify("--base", "master", "--post-merge")
    assert code == 0, json.dumps(report)
    skipped = {c["name"] for c in report["checks"] if c["status"] == "skip"}
    assert {"commits", "docs", "guardrails"} <= skipped


def test_post_merge_still_fails_a_failing_test(gate):
    gate.write("tests/test_x.py", TEST_FILE)
    gate.commit("test: add tests")
    with open(gate.xml, "w") as f:
        f.write(junit(case("test_one")))
    gate.env["FAKE_TEST_XML"] = gate.xml
    code, report = gate.verify("--base", "master", "--post-merge")
    assert code == 1 and "`test_two` never ran" in json.dumps(report)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
