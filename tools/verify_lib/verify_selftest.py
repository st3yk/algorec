"""Self-tests for the verify judge's git-level checks, on scratch repositories.
See docs/guardrails.md."""

import os
import subprocess
from collections.abc import Mapping

import pytest

from tools.verify_lib import gitutil
from tools.verify_lib.bootstrap import base_arg, extract_judge
from tools.verify_lib.commits import check_commits
from tools.verify_lib.coverage import check_coverage, label_to_path
from tools.verify_lib.docs_changed import check_docs, docs_for, load_map
from tools.verify_lib.findings import FAIL, HUMAN, Finding
from tools.verify_lib.gitutil import Commit
from tools.verify_lib.guardrails import check_guardrails, is_guardrail
from tools.verify_lib.report import CheckResult, Report, render_markdown, verdict_of

ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


class Repo:
    def __init__(self, path: str):
        self.path = path
        self.run("init", "-q", "-b", "master")

    def run(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", self.path, *args], check=True, capture_output=True, text=True, env={**os.environ, **ENV}
        ).stdout

    def write(self, files: Mapping[str, str | None]) -> None:
        for rel, text in files.items():
            full = os.path.join(self.path, rel)
            if text is None:
                os.remove(full)
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(text)

    def commit(self, message: str, files: Mapping[str, str | None]) -> str:
        self.write(files)
        self.run("add", "-A")
        self.run("commit", "-q", "--allow-empty", "-m", message)
        return self.run("rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path):
    r = Repo(str(tmp_path))
    r.commit("chore: start", {"README.md": "x\n"})
    return r


def branch_commits(r: Repo) -> list[Commit]:
    return gitutil.commits(r.path, "master", "HEAD")


def on_branch(r: Repo, *commits: tuple[str, Mapping[str, str | None]]) -> list[Commit]:
    r.run("switch", "-q", "-c", "feat/x")
    for message, files in commits:
        r.commit(message, files)
    return branch_commits(r)


def messages(findings: list[Finding]) -> list[str]:
    return [f.message for f in findings]


def test_gitutil_reads_commits_files_and_trailers(repo):
    commits = on_branch(repo, ("feat(a): add a\n\nWhy.\n\nDocs-Unchanged: no behavior change", {"a.py": "x = 1\n"}))
    assert [(c.subject, c.files, c.parents) for c in commits] == [("feat(a): add a", ("a.py",), 1)]
    assert commits[0].trailers("Docs-Unchanged") == ["no behavior change"]


def test_good_commits_pass(repo):
    assert check_commits(on_branch(repo, ("feat(assembler): add a thing", {"a.py": "1\n"}))) == []


@pytest.mark.parametrize(
    "subject, fragment",
    [
        ("update stuff", "Conventional Commit"),
        ("feature: add a", "Conventional Commit"),
        ("feat(Assembler): add a", "Conventional Commit"),
        ("feat: Add a thing", "lowercase"),
        ("feat: " + "x" * 70, "limit is 72"),
        ("WIP: half done", "work-in-progress"),
        ("fixup! feat: add a", "work-in-progress"),
    ],
)
def test_bad_subjects_fail(repo, subject, fragment):
    findings = check_commits(on_branch(repo, (subject, {"a.py": "1\n"})))
    assert findings and all(f.level == FAIL for f in findings)
    assert any(fragment in f.message for f in findings)


def test_an_acronym_at_the_start_is_not_a_capital_letter(repo):
    assert check_commits(on_branch(repo, ("docs: ILP notes for stage 0", {"a.md": "1\n"}))) == []


def test_lock_file_changes_must_be_their_own_commit(repo):
    mixed = on_branch(repo, ("build: bump numpy", {"requirements_lock.txt": "1\n", "steerrec/a.py": "1\n"}))
    assert messages(check_commits(mixed)) == ["lock-file changes must be their own commit (also touches steerrec/a.py)"]


def test_lock_only_commits_pass(repo):
    commits = on_branch(repo, ("build: bump numpy", {"requirements_lock.txt": "1\n", "requirements.in": "numpy\n"}))
    assert check_commits(commits) == []


def test_merge_commits_fail(repo):
    repo.run("switch", "-q", "-c", "feat/x")
    repo.commit("feat: a", {"a.py": "1\n"})
    repo.run("switch", "-q", "-c", "side", "master")
    repo.commit("feat: b", {"b.py": "1\n"})
    repo.run("switch", "-q", "feat/x")
    repo.run("merge", "-q", "--no-ff", "-m", "Merge branch side", "side")
    assert any("merge commits" in f.message for f in check_commits(branch_commits(repo)))


def test_the_docs_map_covers_every_steerrec_module():
    mapping = load_map()
    for module in ("items", "registry", "targets", "assembler", "synthetic", "demo"):
        assert docs_for(f"steerrec/{module}.py", mapping), module
    assert docs_for("proto/steerrec/v1/recommender.proto", mapping) == ["docs/service-contract.md"]
    assert docs_for("tools/verify_lib/verify.py", mapping) == ["docs/guardrails.md"]
    assert docs_for("docs/README.md", mapping) == []


def test_a_feature_without_its_docs_page_fails(repo):
    commits = on_branch(repo, ("feat(assembler): change a", {"steerrec/assembler.py": "1\n"}))
    findings = check_docs(commits, load_map())
    assert [(f.level, f.check) for f in findings] == [(FAIL, "docs")]
    assert "docs/code/assembler.md" in findings[0].message


def test_a_feature_with_its_docs_page_passes(repo):
    files = {"steerrec/assembler.py": "1\n", "docs/code/assembler.md": "x\n"}
    assert check_docs(on_branch(repo, ("feat(assembler): change a", files)), load_map()) == []


def test_non_behavior_commit_types_are_exempt(repo):
    commits = on_branch(repo, ("refactor(assembler): rename", {"steerrec/assembler.py": "1\n"}))
    assert check_docs(commits, load_map()) == []


def test_the_docs_unchanged_trailer_asks_a_human(repo):
    message = "fix(assembler): tweak\n\nDocs-Unchanged: the page already describes this"
    findings = check_docs(on_branch(repo, (message, {"steerrec/assembler.py": "1\n"})), load_map())
    assert [f.level for f in findings] == [HUMAN]
    assert "the page already describes this" in findings[0].message


def test_the_docs_page_must_change_in_the_same_commit(repo):
    commits = on_branch(
        repo,
        ("feat(assembler): change a", {"steerrec/assembler.py": "1\n"}),
        ("docs: describe a", {"docs/code/assembler.md": "x\n"}),
    )
    assert [f.level for f in check_docs(commits, load_map())] == [FAIL]


TEST_FILE = """import pytest


@pytest.mark.parametrize("seed", range(30))
def test_a(seed):
    assert seed >= 0
    assert seed < 100


def test_b():
    with pytest.raises(ValueError):
        int("x")
"""
BUILD = 'py_test(\n    name = "test_x",\n    srcs = ["test_x.py"],\n)\n'


def guard(repo: Repo, head_files: Mapping[str, str | None], base_files: Mapping[str, str | None] | None = None):
    repo.commit("test: base", base_files or {"tests/test_x.py": TEST_FILE, "tests/BUILD.bazel": BUILD})
    repo.run("switch", "-q", "-c", "feat/x")
    repo.commit("test: change", head_files)
    mb = gitutil.merge_base(repo.path, "master", "HEAD")
    return check_guardrails(
        gitutil.changed_files(repo.path, mb, "HEAD"),
        gitutil.ls_tree(repo.path, mb, "."),
        gitutil.ls_tree(repo.path, "HEAD", "."),
        lambda p: gitutil.show(repo.path, mb, p),
        lambda p: gitutil.show(repo.path, "HEAD", p),
    )


def test_adding_tests_and_asserts_is_not_flagged(repo):
    more = TEST_FILE + "\n\ndef test_c():\n    assert True\n"
    assert (
        guard(
            repo, {"tests/test_x.py": more.replace("    assert seed < 100\n", "    assert seed < 100\n    assert 1\n")}
        )
        == []
    )


def test_reformatting_an_assert_is_not_flagged(repo):
    reformatted = TEST_FILE.replace("    assert seed < 100\n", "    assert (\n        seed < 100\n    )\n")
    assert guard(repo, {"tests/test_x.py": reformatted}) == []


def test_moving_a_test_to_another_file_is_not_flagged(repo):
    head = {"tests/test_x.py": TEST_FILE.split("\n\ndef test_b")[0] + "\n", "tests/test_y.py": TEST_FILE}
    assert all("removed" not in m for m in messages(guard(repo, head)))


@pytest.mark.parametrize(
    "change, fragment",
    [
        (lambda t: t.replace("    assert seed < 100\n", ""), "lost or changed a check: `assert seed < 100`"),
        (lambda t: t.replace("seed < 100", "seed < 1000"), "lost or changed a check"),
        (lambda t: t.replace("range(30)", "range(3)"), "lost or changed `@pytest.mark.parametrize"),
        (lambda t: t.replace("def test_b", "def helper_b"), "test `test_b` was removed or renamed"),
        (lambda t: t.replace("def test_b():", "@pytest.mark.skip\ndef test_b():"), "gained a skip or xfail"),
        (lambda t: t.replace('        int("x")', '        pytest.skip("later")\n        int("x")'), "gained a skip"),
        (lambda t: t.replace("pytest.raises(ValueError)", "pytest.raises(Exception)"), "lost or changed a check"),
    ],
)
def test_weakening_a_test_asks_a_human(repo, change, fragment):
    findings = guard(repo, {"tests/test_x.py": change(TEST_FILE)})
    assert findings and all(f.level == HUMAN for f in findings)
    assert any(fragment in f.message for f in findings), messages(findings)


def test_a_new_skipped_test_asks_a_human(repo):
    head = TEST_FILE + "\n\n@pytest.mark.xfail\ndef test_new():\n    assert False\n"
    assert "new test `test_new` is skipped or xfailed" in messages(guard(repo, {"tests/test_x.py": head}))


def test_removing_or_hiding_a_py_test_rule_asks_a_human(repo):
    manual = BUILD.replace(")\n", '    tags = ["manual"],\n)\n')
    assert "py_test rule is now tagged manual, so //... skips it" in messages(
        guard(repo, {"tests/BUILD.bazel": manual})
    )


def test_removing_a_py_test_rule_asks_a_human(tmp_path):
    r = Repo(str(tmp_path))
    r.commit("chore: start", {"README.md": "x\n"})
    assert "py_test rule was removed" in messages(guard(r, {"tests/BUILD.bazel": "\n"}))


def test_editing_a_guardrail_file_asks_a_human(repo):
    findings = guard(repo, {"tools/verify_lib/commits.py": "TYPES = ()\n", "ruff.toml": "x\n"})
    assert sorted((f.where, f.level) for f in findings) == [
        ("ruff.toml", HUMAN),
        ("tools/verify_lib/commits.py", HUMAN),
    ]


GOLDEN = "message p.M\nfield p.M 1 a optional TYPE_STRING json=a\n"


def test_a_growing_golden_is_fine(repo):
    head = {"proto/recommender.fields.golden": GOLDEN + "field p.M 2 b optional TYPE_STRING json=b\n"}
    assert guard(repo, head, {"proto/recommender.fields.golden": GOLDEN}) == []


def test_a_hand_edited_golden_that_hides_a_break_fails(repo):
    head = {"proto/recommender.fields.golden": "message p.M\n"}
    findings = guard(repo, head, {"proto/recommender.fields.golden": GOLDEN})
    assert [f.level for f in findings] == [FAIL]
    assert "was removed without `reserved`" in findings[0].message


def test_a_deleted_golden_fails(repo):
    findings = guard(repo, {"proto/recommender.fields.golden": None}, {"proto/recommender.fields.golden": GOLDEN})
    assert [f.message for f in findings] == ["the contract golden was deleted"]


@pytest.mark.parametrize(
    "path, expected",
    [
        ("tools/verify", True),
        ("tools/verify_lib/commits.py", True),
        (".github/workflows/verify.yml", True),
        (".claude/settings.json", True),
        ("BUILD.bazel", False),
        ("steerrec/assembler.py", False),
        ("proto/recommender.fields.golden", False),
    ],
)
def test_guardrail_paths(path, expected):
    assert is_guardrail(path) is expected


def test_coverage_flags_files_no_check_sees():
    tracked = ["README.md", "steerrec/a.py", "steerrec/sub/b.py", "tests/test_c.py", ".github/x.yml"]
    seen = {
        "repo": {"README.md", "steerrec/a.py", "tests/test_c.py"},
        "lint": {"steerrec/a.py", "tests/test_c.py"},
        "mypy": {"steerrec/a.py"},
    }
    findings = check_coverage(tracked, seen)
    assert sorted((f.where, "ruff" in f.message, "mypy" in f.message) for f in findings) == [
        ("steerrec/sub/b.py", False, False),
        ("steerrec/sub/b.py", False, True),
        ("steerrec/sub/b.py", True, False),
    ]


def test_labels_map_to_repo_paths():
    assert label_to_path("//:README.md") == "README.md"
    assert label_to_path("//steerrec:assembler.py") == "steerrec/assembler.py"
    assert label_to_path("@pypi//numpy:x.py") is None


@pytest.mark.parametrize(
    "statuses, levels, verdict",
    [
        (["pass"], [], "PASS"),
        (["pass", "skip"], [], "PASS"),
        (["pass"], [HUMAN], "NEEDS_HUMAN"),
        (["needs_human"], [], "NEEDS_HUMAN"),
        (["pass", "fail"], [HUMAN], "FAIL"),
        (["pass"], [FAIL, HUMAN], "FAIL"),
        (["fail", "error"], [], "ERROR"),
        ([], [], "ERROR"),
    ],
)
def test_verdicts(statuses, levels, verdict):
    checks = [CheckResult(f"c{i}", s) for i, s in enumerate(statuses)]
    findings = [Finding("x", level, "m") for level in levels]
    assert verdict_of(checks, findings) == verdict


def test_the_report_names_the_sha_and_how_to_reproduce():
    report = Report(
        mode="gate", sha="a" * 40, base="master", merge_base="b" * 40, reproduce="tools/verify --base master"
    )
    report.checks = [CheckResult("test", "fail", 1.0, "bazel exit 3", "FAIL: //t:x")]
    text = render_markdown(report)
    assert "FAIL" in text and "aaaaaaaaaaaa" in text and "Reproduce: `tools/verify --base master`" in text
    assert report.exit_code == 1
    assert '"verdict": "FAIL"' in report.to_json()


def test_base_arg_parsing():
    assert base_arg(["--base", "origin/x"]) == "origin/x"
    assert base_arg(["--deep", "--base=main"]) == "main"
    assert base_arg(["--deep"]) is None


def test_the_judge_is_extracted_from_the_given_ref(repo, tmp_path_factory):
    repo.commit(
        "chore: judge",
        {
            "tools/__init__.py": "",
            "tools/verify_lib/__init__.py": "",
            "tools/verify_lib/verify.py": "BASE = True\n",
        },
    )
    base = repo.run("rev-parse", "HEAD").strip()
    repo.commit("chore: tamper", {"tools/verify_lib/verify.py": "BASE = False\n"})
    dest = str(tmp_path_factory.mktemp("judge"))
    assert extract_judge(repo.path, base, dest)
    with open(os.path.join(dest, "tools/verify_lib/verify.py")) as f:
        assert f.read() == "BASE = True\n"


def test_no_judge_is_extracted_from_a_ref_without_one(repo, tmp_path_factory):
    assert not extract_judge(repo.path, "HEAD", str(tmp_path_factory.mktemp("judge")))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
