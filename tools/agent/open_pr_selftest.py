"""Self-tests for tools/agent/open_pr.sh: a PR is opened only when the base's judge says the
change is ready. See docs/guardrails.md."""

import os
import shutil
import subprocess

import pytest

SCRIPT = os.path.join(os.environ.get("TEST_SRCDIR", ""), "_main", "tools", "agent", "open_pr.sh")
ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}
FAKE_VERIFY = """#!/usr/bin/env bash
repo="$(git rev-parse --show-toplevel)"
sha="$(git rev-parse HEAD)"
mkdir -p "$repo/.verify/reports"
printf '{"verdict": "%s", "human_kind": "%s"}' "$FAKE_VERDICT" "$FAKE_KIND" > "$repo/.verify/reports/${sha:0:12}.json"
exit "$FAKE_CODE"
"""
FAKE_GH = """#!/bin/sh
echo "$@" >> "$GH_LOG"
if [ "$1 $2" = "pr list" ]; then
  echo "${FAKE_PR_NUMBER:-}"
fi
exit 0
"""


class Repo:
    def __init__(self, root: str):
        self.root = root
        self.work = os.path.join(root, "work")
        self.origin = os.path.join(root, "origin.git")
        bin_dir = os.path.join(root, "bin")
        os.makedirs(bin_dir)
        self._script(os.path.join(bin_dir, "gh"), FAKE_GH)
        self.gh_log = os.path.join(root, "gh.log")
        self.env = {
            **os.environ,
            **ENV,
            "PATH": bin_dir + os.pathsep + os.environ.get("PATH", ""),
            "GH_LOG": self.gh_log,
            "FAKE_CODE": "0",
            "FAKE_VERDICT": "PASS",
            "FAKE_KIND": "",
        }
        self.run("git", "init", "-q", "--bare", "-b", "master", self.origin, cwd=root)
        self.run("git", "clone", "-q", self.origin, self.work, cwd=root)
        self._script(os.path.join(self.work, "tools", "verify"), FAKE_VERIFY)
        self._script(os.path.join(self.work, "tools", "pr_body"), "#!/bin/sh\necho body\n")
        os.makedirs(os.path.join(self.work, "tools", "agent"))
        shutil.copy(SCRIPT, os.path.join(self.work, "tools", "agent", "open_pr.sh"))
        with open(os.path.join(self.work, ".gitignore"), "w") as f:
            f.write(".verify/\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "chore: start")
        self.git("push", "-q", "origin", "master")
        self.git("switch", "-q", "-c", "feat/demo")
        os.makedirs(os.path.join(self.work, "design", "demo"))
        with open(os.path.join(self.work, "design", "demo", "summary.md"), "w") as f:
            f.write("# PR summary: Demo change\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "docs: add the demo summary")

    @staticmethod
    def _script(path: str, text: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        os.chmod(path, 0o755)

    def run(self, *args: str, cwd: str | None = None) -> str:
        result = subprocess.run(args, cwd=cwd or self.work, check=True, capture_output=True, text=True, env=self.env)
        return result.stdout

    def git(self, *args: str) -> str:
        return self.run("git", *args)

    def open_pr(self, *args: str) -> subprocess.CompletedProcess[str]:
        script = os.path.join(self.work, "tools", "agent", "open_pr.sh")
        return subprocess.run(["bash", script, *args], cwd=self.work, capture_output=True, text=True, env=self.env)

    def remote_has(self, branch: str) -> bool:
        heads = self.run("git", "ls-remote", "--heads", self.origin, branch)
        return bool(heads.strip())

    def gh_calls(self) -> list[str]:
        if not os.path.exists(self.gh_log):
            return []
        with open(self.gh_log) as f:
            return f.read().splitlines()


@pytest.fixture
def repo(tmp_path):
    return Repo(str(tmp_path))


def test_a_pass_pushes_and_opens_a_ready_pr(repo):
    result = repo.open_pr("demo")
    assert result.returncode == 0, result.stderr
    assert repo.remote_has("feat/demo")
    creates = [c for c in repo.gh_calls() if c.startswith("pr create")]
    assert len(creates) == 1 and "--title Demo change" in creates[0] and "--label" not in creates[0]
    assert "--draft" not in creates[0]


def test_a_soft_needs_human_opens_a_labelled_pr(repo):
    repo.env.update(FAKE_CODE="2", FAKE_VERDICT="NEEDS_HUMAN", FAKE_KIND="soft")
    assert repo.open_pr("demo").returncode == 0
    creates = [c for c in repo.gh_calls() if c.startswith("pr create")]
    assert len(creates) == 1 and "--label needs-human" in creates[0]


@pytest.mark.parametrize(
    "code, verdict, kind",
    [("2", "NEEDS_HUMAN", "hard"), ("2", "NEEDS_HUMAN", ""), ("1", "FAIL", ""), ("3", "ERROR", "")],
)
def test_anything_else_pushes_nothing_and_opens_no_pr(repo, code, verdict, kind):
    repo.env.update(FAKE_CODE=code, FAKE_VERDICT=verdict, FAKE_KIND=kind)
    result = repo.open_pr("demo")
    assert result.returncode == int(code)
    assert not repo.remote_has("feat/demo")
    assert repo.gh_calls() == []


def test_an_existing_pr_is_updated_and_marked_ready(repo):
    repo.env["FAKE_PR_NUMBER"] = "7"
    result = repo.open_pr("demo")
    assert result.returncode == 0 and "updated PR #7" in result.stdout
    calls = repo.gh_calls()
    assert "pr edit 7 --body-file" in " ".join(calls) and any(c.startswith("pr ready 7") for c in calls)
    assert not any(c.startswith("pr create") for c in calls)


def test_only_a_clean_feature_branch_is_accepted(repo):
    repo.git("switch", "-q", "master")
    assert repo.open_pr("demo").returncode == 64
    repo.git("switch", "-q", "feat/demo")
    with open(os.path.join(repo.work, "design", "demo", "summary.md"), "a") as f:
        f.write("dirty\n")
    assert repo.open_pr("demo").returncode == 65
    assert repo.gh_calls() == []


def test_a_base_without_a_judge_opens_nothing(repo):
    repo.git("switch", "-q", "master")
    repo.git("rm", "-q", "tools/verify")
    repo.git("commit", "-qm", "chore: drop the judge")
    repo.git("push", "-q", "origin", "master")
    repo.git("switch", "-q", "feat/demo")
    result = repo.open_pr("demo")
    assert result.returncode == 3 and "no trusted judge" in result.stderr
    assert not repo.remote_has("feat/demo")


def test_bad_arguments_are_refused(repo):
    assert repo.open_pr().returncode == 64
    assert repo.open_pr("demo", "--base").returncode == 64


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
