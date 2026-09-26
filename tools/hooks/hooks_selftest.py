"""Self-tests for the Claude Code and git hook helpers. See docs/guardrails.md."""

import io
import json
import os
import subprocess

import pytest

from tools.hooks import commit_msg, on_stop, post_edit, quick, session_start

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


def run_post_edit(monkeypatch, event: dict[str, object]) -> int:
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
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"stop_hook_active": True})))
    assert on_stop.main() == 0


def test_stop_skips_verify_on_an_unchanged_green_tree(repo, monkeypatch):
    failing_verify(repo)
    (repo / ".verify").mkdir()
    (repo / ".verify" / "last-fast-green").write_text(on_stop.fingerprint(str(repo)))
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert on_stop.main() == 0


def test_stop_blocks_when_verify_fails(repo, monkeypatch, capsys):
    failing_verify(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert on_stop.main() == 2
    assert "FAIL test (fast)" in capsys.readouterr().err


def test_session_start_prints_the_build_log_state(repo, capsys):
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
