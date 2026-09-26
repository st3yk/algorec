"""Self-tests for tools/agent/start_build.sh on scratch repositories with a local origin.
See docs/guardrails.md."""

import os
import shutil
import subprocess

import pytest

SCRIPT = os.path.join(os.environ.get("TEST_SRCDIR", ""), "_main", "tools", "agent", "start_build.sh")
ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


@pytest.fixture
def repo(tmp_path):
    env = {**os.environ, **ENV}
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(origin)], check=True, env=env)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, env=env, capture_output=True)
    (work / "README.md").write_text("x\n")
    (work / "tools" / "agent").mkdir(parents=True)
    shutil.copy(SCRIPT, work / "tools" / "agent" / "start_build.sh")
    for args in (["add", "-A"], ["commit", "-qm", "chore: start"], ["push", "-q", "origin", "master"]):
        subprocess.run(["git", "-C", str(work), *args], check=True, env=env, capture_output=True)
    (work / "design" / "demo").mkdir(parents=True)
    (work / "design" / "demo" / "plan.md").write_text("# Demo plan\n")
    return work


def run(repo, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(repo / "tools" / "agent" / "start_build.sh"), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, **ENV},
    )


def test_dry_run_prints_every_step_and_changes_nothing(repo):
    result = run(repo, "demo", "--dry-run")
    assert result.returncode == 0, result.stderr
    for step in ("worktree add", "commit", "push", "gh pr create --draft", "claude -p"):
        assert step in result.stdout
    assert not (repo / ".claude").exists()
    assert "feat/demo" not in subprocess.run(["git", "-C", str(repo), "branch"], capture_output=True, text=True).stdout


def test_gate_mode_stops_before_starting_the_build(repo):
    result = run(repo, "demo", "--dry-run", "--gate")
    assert result.returncode == 0 and "claude -p" in result.stdout and "--permission-mode acceptEdits" in result.stdout
    assert "+ claude" not in result.stdout


@pytest.mark.parametrize(
    "args, code",
    [
        ((), 64),
        (("Bad_Slug", "--dry-run"), 64),
        (("demo", "--base"), 64),
        (("demo", "--unknown"), 64),
        (("missing", "--dry-run"), 66),
    ],
)
def test_bad_arguments_are_refused(repo, args, code):
    assert run(repo, *args).returncode == code


def test_an_existing_local_or_remote_branch_is_refused(repo):
    env = {**os.environ, **ENV}
    subprocess.run(["git", "-C", str(repo), "branch", "feat/demo"], check=True, env=env)
    assert run(repo, "demo", "--dry-run").returncode == 73
    subprocess.run(
        ["git", "-C", str(repo), "push", "-q", "origin", "feat/demo"], check=True, env=env, capture_output=True
    )
    subprocess.run(["git", "-C", str(repo), "branch", "-q", "-D", "feat/demo"], check=True, env=env)
    result = run(repo, "demo", "--dry-run")
    assert result.returncode == 73 and "on origin" in result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
