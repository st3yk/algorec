"""Self-tests for the Claude Code and git hook helpers. See docs/guardrails.md."""

import io
import json
import os
import subprocess
from collections.abc import Mapping

import pytest

from tools.hooks import commit_msg, on_stop, post_edit, pre_bash, quick, session_start

RUNFILES = os.path.join(os.environ.get("TEST_SRCDIR", ""), "_main")

ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    subprocess.run(["git", "init", "-q", "-b", "master", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".verify/\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text("# Page\n")
    (tmp_path / "steerrec").mkdir()
    (tmp_path / "steerrec" / "a.py").write_text('"""A. See docs/page.md."""\n\nX = 1\n')
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "chore: start"], check=True)
    monkeypatch.setattr(quick, "ruff_bin", lambda repo: None)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    return tmp_path


def test_a_clean_file_has_no_problems(repo):
    assert quick.check_files(str(repo), ["steerrec/a.py", "docs/page.md", "missing.py"]) == []


def test_an_inline_comment_is_reported(repo):
    (repo / "steerrec" / "a.py").write_text('"""A. See docs/page.md."""\n\nX = 1  # why\n')
    problems = quick.check_files(str(repo), ["steerrec/a.py"])
    assert len(problems) == 1 and "[no-comments]" in problems[0]


def run_post_edit(monkeypatch, event: Mapping[str, object]) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    return post_edit.main()


def test_post_edit_sends_problems_back_with_exit_2(repo, monkeypatch, capsys):
    (repo / "steerrec" / "a.py").write_text('"""A. See docs/page.md."""\n\n\ndef f():\n    """Doc."""\n')
    assert run_post_edit(monkeypatch, {"tool_input": {"file_path": str(repo / "steerrec" / "a.py")}}) == 2
    assert "[no-docstrings]" in capsys.readouterr().err


def test_post_edit_ignores_clean_files_and_files_outside_the_repo(repo, monkeypatch, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "x.py"
    outside.write_text("X = 1  # fine here\n")
    assert run_post_edit(monkeypatch, {"tool_input": {"file_path": str(repo / "steerrec" / "a.py")}}) == 0
    assert run_post_edit(monkeypatch, {"tool_input": {"file_path": str(outside)}}) == 0
    assert run_post_edit(monkeypatch, {"tool_input": {}}) == 0


def test_the_stop_fingerprint_changes_with_tracked_and_untracked_edits(repo):
    first = on_stop.fingerprint(str(repo))
    assert on_stop.fingerprint(str(repo)) == first
    (repo / "steerrec" / "a.py").write_text("X = 2\n")
    second = on_stop.fingerprint(str(repo))
    (repo / "new.py").write_text("Y = 1\n")
    third = on_stop.fingerprint(str(repo))
    (repo / "new.py").write_text("Y = 2\n")
    assert len({first, second, third, on_stop.fingerprint(str(repo))}) == 4


def failing_verify(repo) -> None:
    tools = repo / "tools"
    tools.mkdir(exist_ok=True)
    (tools / "verify").write_text("#!/bin/sh\necho 'FAIL test (fast)'\nexit 1\n")
    (tools / "verify").chmod(0o755)


def test_stop_lets_a_retry_through(repo, monkeypatch):
    failing_verify(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"stop_hook_active": True, "cwd": str(repo)})))
    assert on_stop.main() == 0


def test_stop_skips_verify_on_an_unchanged_green_tree(repo, monkeypatch):
    failing_verify(repo)
    (repo / ".verify").mkdir()
    (repo / ".verify" / "last-fast-green").write_text(on_stop.fingerprint(str(repo)))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(repo)})))
    assert on_stop.main() == 0


def test_stop_blocks_when_verify_fails(repo, monkeypatch, capsys):
    failing_verify(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(repo)})))
    assert on_stop.main() == 2
    assert "FAIL test (fast)" in capsys.readouterr().err


def test_stop_caches_a_red_result_for_an_unchanged_tree(repo, monkeypatch):
    tools = repo / "tools"
    tools.mkdir()
    (tools / "verify").write_text(f"#!/bin/sh\necho run >> {repo}/.git/verify-runs\necho 'FAIL x'\nexit 1\n")
    (tools / "verify").chmod(0o755)
    for _ in range(2):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(repo)})))
        assert on_stop.main() == 2
    assert (repo / ".git" / "verify-runs").read_text().count("run") == 1


def test_post_edit_checks_the_repo_the_file_is_in(repo, monkeypatch, capsys):
    nested = repo / "nested"
    subprocess.run(["git", "init", "-q", str(nested)], check=True)
    (nested / "steerrec").mkdir()
    (nested / "docs").mkdir()
    (nested / "docs" / "page.md").write_text("# Page\n")
    (nested / "steerrec" / "b.py").write_text('"""B. See docs/page.md."""\n\nX = 1  # why\n')
    event = {"tool_input": {"file_path": "nested/steerrec/b.py"}, "cwd": str(repo)}
    assert run_post_edit(monkeypatch, event) == 2
    assert "steerrec/b.py" in capsys.readouterr().err


@pytest.mark.parametrize(
    "command",
    [
        "git push origin feat/x",
        "git push -u origin feat/x",
        "git push origin feat/x:feat/x",
        "git status && git push origin feat/a-b.c",
        "echo git push origin master",
        "git push -u origin feat/x 2>&1 | tail -3",
        "git push origin feat/x > /dev/null",
        "git push -o ci.skip origin feat/x",
        "git push --push-option=ci.skip origin feat/x",
        "/usr/bin/git push -u origin feat/x",
    ],
)
def test_the_push_guard_allows_feature_branch_pushes(command):
    assert pre_bash.push_problems(command) == []


@pytest.mark.parametrize(
    "command, fragment",
    [
        ("git push origin master", "only feat/*"),
        ("git push origin feat/x +HEAD:master", "force push"),
        ("git push origin feat/x :master", "deletes a remote branch"),
        ("git push origin feat/x feat/x:refs/heads/master", "only feat/*"),
        ("git push origin feat/x --mirror", "--mirror"),
        ("git push --force origin feat/x", "--force"),
        ("git push --force-with-lease origin feat/x", "--force-with-lease"),
        ("git push origin", "name the remote"),
        ("git -C . push origin HEAD:master", "only feat/*"),
        ("FOO=1 git push origin main", "only feat/*"),
        ("git push -uf origin feat/x", "`-f` (in `-uf`)"),
        ("/usr/bin/git push origin master", "only feat/*"),
        ("command git push origin master", "only feat/*"),
        ("env FOO=1 git push origin master", "only feat/*"),
        ('bash -c "git push origin master"', "only feat/*"),
        ("sudo -E git push --force origin feat/x", "--force"),
        ("git push -d origin feat/x", "`-d`"),
    ],
)
def test_the_push_guard_rejects_everything_else(command, fragment):
    problems = pre_bash.push_problems(command)
    assert problems and any(fragment in p for p in problems), problems


def pre_push(repo, verify_code: int, stdin: str) -> int:
    tools = repo / "tools"
    tools.mkdir(exist_ok=True)
    (tools / "verify").write_text(f"#!/bin/sh\nexit {verify_code}\n")
    (tools / "verify").chmod(0o755)
    hook = os.path.join(RUNFILES, "tools/githooks/pre-push")
    return subprocess.run(["bash", hook], cwd=repo, input=stdin, capture_output=True, text=True).returncode


@pytest.mark.parametrize("verdict, allowed", [(0, True), (2, True), (1, False), (3, False)])
def test_pre_push_follows_the_verdict(repo, verdict, allowed):
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    stdin = f"refs/heads/feat/x {head} refs/heads/feat/x {'0' * 40}\n"
    assert (pre_push(repo, verdict, stdin) == 0) is allowed


def test_pre_push_refuses_the_default_branch_and_other_commits(repo):
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert pre_push(repo, 0, f"refs/heads/master {head} refs/heads/master {'0' * 40}\n") == 1
    assert pre_push(repo, 0, f"refs/heads/feat/x {'1' * 40} refs/heads/feat/x {'0' * 40}\n") == 1


def test_session_start_prints_the_build_log_state(repo, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(repo)})))
    (repo / "design" / "x").mkdir(parents=True)
    (repo / "design" / "x" / "build-log.md").write_text("# Log\n\n## Current state\n\n- Next: M2\n\n## Milestones\n")
    assert session_start.main() == 0
    out = capsys.readouterr().out
    assert "branch master" in out and "- Next: M2" in out and "## Milestones" not in out


@pytest.mark.parametrize(
    "message, code",
    [
        ("feat(assembler): add a thing\n\nWhy.\n", 0),
        ("update stuff\n", 1),
        ("# a comment line git strips\nfix: handle x\n", 0),
    ],
)
def test_commit_msg_applies_the_gate_rules(repo, monkeypatch, message, code):
    monkeypatch.chdir(repo)
    path = repo / "MSG"
    path.write_text(message)
    assert commit_msg.main(str(path)) == code


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
