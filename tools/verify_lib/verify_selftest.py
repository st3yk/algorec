"""Self-tests for the verify judge's git-level checks, on scratch repositories.
See docs/guardrails.md."""

import os
import re
import subprocess
from collections.abc import Mapping

import pytest

from tools.verify_lib import gitutil
from tools.verify_lib.commits import check_commits
from tools.verify_lib.coverage import check_coverage, source_paths
from tools.verify_lib.docs_changed import check_docs, docs_for, load_map
from tools.verify_lib.evidence import required_tests
from tools.verify_lib.findings import FAIL, HUMAN, Finding
from tools.verify_lib.gitutil import Commit
from tools.verify_lib.guardrails import check_guardrails, is_guardrail
from tools.verify_lib.pr_body import build, section
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
        ('Revert "feat: add a" and more', "Conventional Commit"),
    ],
)
def test_bad_subjects_fail(repo, subject, fragment):
    findings = check_commits(on_branch(repo, (subject, {"a.py": "1\n"})))
    assert findings and all(f.level == FAIL for f in findings)
    assert any(fragment in f.message for f in findings)


def test_gits_default_revert_subject_passes(repo):
    assert check_commits(on_branch(repo, ('Revert "feat(a): add a"', {"a.py": "1\n"}))) == []


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
    assert docs_for("proto/BUILD.bazel", mapping) == []
    assert docs_for("proto/recommender.fields.golden", mapping) == []
    assert docs_for("tools/verify_lib/verify.py", mapping) == ["docs/guardrails.md"]
    assert docs_for("tools/verify", mapping) == ["docs/guardrails.md"]
    assert docs_for("tools/lint/BUILD.bazel", mapping) == []
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


def test_editing_a_guardrail_file_asks_a_human_once_per_area(repo):
    files = {"tools/verify_lib/commits.py": "TYPES = ()\n", "tools/verify_lib/x.py": "\n", "ruff.toml": "x\n"}
    findings = guard(repo, files)
    assert sorted((f.where, f.level) for f in findings) == [("ruff.toml", HUMAN), ("tools/verify_lib/", HUMAN)]
    assert "commits.py, x.py" in [f.message for f in findings if f.where == "tools/verify_lib/"][0]


def test_skip_names_inside_strings_are_not_skips(repo):
    head = TEST_FILE + '\n\ndef test_text():\n    assert "pytest.mark.skip" in "@pytest.mark.skip pytest.skip("\n'
    assert guard(repo, {"tests/test_x.py": head}) == []


def test_a_renamed_test_file_keeps_its_protection(repo):
    head = {"tests/test_x.py": None, "tests/test_y.py": TEST_FILE.replace("    assert seed < 100\n", "")}
    assert "`test_a` lost or changed a check: `assert seed < 100`" in messages(guard(repo, head))


def test_module_wide_skips_and_changed_module_settings_ask_a_human(repo):
    marked = guard(repo, {"tests/test_x.py": TEST_FILE + "\npytestmark = pytest.mark.skip\n"})
    assert any("module-wide pytest marks added" in m for m in messages(marked))


def test_a_loosened_module_level_tolerance_asks_a_human(tmp_path):
    r = Repo(str(tmp_path))
    r.commit("chore: start", {"README.md": "x\n"})
    base = {"tests/test_x.py": "EPS = 0.03\n" + TEST_FILE, "tests/BUILD.bazel": BUILD}
    findings = guard(r, {"tests/test_x.py": "EPS = 1.0\n" + TEST_FILE}, base)
    assert "a module-level test setting was removed or changed: `EPS = 0.03`" in messages(findings)


def test_asserts_in_helper_functions_are_protected_too(tmp_path):
    r = Repo(str(tmp_path))
    r.commit("chore: start", {"README.md": "x\n"})
    helper = "\n\ndef brute_force(x):\n    assert x > 0\n    return x\n"
    base = {"tests/test_x.py": TEST_FILE + helper, "tests/BUILD.bazel": BUILD}
    findings = guard(r, {"tests/test_x.py": TEST_FILE + helper.replace("    assert x > 0\n", "")}, base)
    assert "`brute_force` lost or changed a check: `assert x > 0`" in messages(findings)


def test_a_skip_through_an_imported_mark_asks_a_human(repo):
    head = TEST_FILE.replace("def test_b():", "@mark.skip\ndef test_b():")
    assert any("gained a skip" in m for m in messages(guard(repo, {"tests/test_x.py": head})))


def test_deselecting_tests_through_a_rule_attribute_asks_a_human(repo):
    head = BUILD.replace(")\n", '    env = {"PYTEST_ADDOPTS": "-k not test_a"},\n)\n')
    assert any("py_test rule changed how it runs" in m for m in messages(guard(repo, {"tests/BUILD.bazel": head})))


def test_an_early_exit_above_the_footer_asks_a_human(repo):
    footer = 'if __name__ == "__main__":\n    raise SystemExit(pytest.main([__file__, "-q"]))\n'
    early = TEST_FILE + '\nif __name__ == "__main__":\n    raise SystemExit(0)\n\n\n' + footer
    assert any("module-level code added" in m for m in messages(guard(repo, {"tests/test_x.py": early})))


def test_a_new_test_file_with_the_standard_footer_is_not_flagged(repo):
    footer = 'if __name__ == "__main__":\n    raise SystemExit(pytest.main([__file__, "-q"]))\n'
    new = "import pytest\n\n\ndef test_n():\n    assert True\n\n\n" + footer
    assert guard(repo, {"tests/test_new.py": new}) == []


def test_a_skip_alias_asks_a_human(repo):
    head = "_off = pytest.mark.skip\n" + TEST_FILE.replace("def test_b():", "@_off\ndef test_b():")
    assert any("module-level code added" in m for m in messages(guard(repo, {"tests/test_x.py": head})))


def test_an_early_return_asks_a_human(repo):
    head = TEST_FILE.replace("    assert seed >= 0\n", "    return\n    assert seed >= 0\n")
    assert any("gained a `return`" in m for m in messages(guard(repo, {"tests/test_x.py": head})))


def test_a_changed_load_line_asks_a_human(repo):
    head = 'load("//tests:defs.bzl", "py_test")\n\n' + BUILD
    assert "a BUILD file changed which rules it loads" in messages(guard(repo, {"tests/BUILD.bazel": head}))


def test_required_tests_cover_module_and_class_tests():
    text = (
        "def test_a():\n    pass\n\n\ndef helper():\n    pass\n\n\nclass TestK:\n    def test_b(self):\n        pass\n"
    )
    files = {"tests/test_x.py": text, "tests/conftest.py": "def test_no():\n    pass\n", "steerrec/a.py": text}
    assert required_tests(list(files), files.get) == {("tests.test_x", "test_a"), ("tests.test_x.TestK", "test_b")}


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
        ("tests/conftest.py", True),
        ("conftest.py", True),
        ("tools/bazel", True),
        ("MODULE.bazel", True),
        (".bazelversion", True),
        ("tests/defs.bzl", True),
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


def test_cquery_output_maps_to_source_paths():
    out = "README.md\nsteerrec/a.py\nbazel-out/k8-fastbuild/bin/x.py\nexternal/pypi/y.py\n"
    assert source_paths(out) == {"README.md", "steerrec/a.py"}


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


def test_section_reads_one_markdown_section():
    text = "## Summary\n\nOne.\n\n## Why\n\nTwo.\n### Sub\nMore.\n"
    assert section(text, "Summary") == "One."
    assert section(text, "Why") == "Two.\n### Sub\nMore."
    assert section(text, "Missing") == ""


def pr_repo(repo: Repo) -> str:
    repo.run("switch", "-q", "-c", "feat/x")
    repo.commit("feat(a): add a", {"a.py": "1\n"})
    repo.commit("fix(a): handle b\n\nReview finding (M1 round 1, major).", {"a.py": "2\n"})
    repo.write(
        {
            "design/s/summary.md": "## Summary\n\nAdds a.\n\n## Why\n\nBecause.\n\n## Not done\n\nC.\n",
            "design/s/build-log.md": "## Plan deviations\n\n| Step | Deviation |\n|---|---|\n| 1 | x |\n",
            "design/s/review-log.md": "## M1 · Round 1\n\n**Reviewed**: `a..b` · **Verdict**: ITERATE\n",
        }
    )
    return repo.run("rev-parse", "HEAD").strip()


def test_the_pr_body_has_every_section_and_only_real_commits(repo):
    head = pr_repo(repo)
    report = Report(mode="gate", sha=head, base="master", merge_base=gitutil.merge_base(repo.path, "master", head))
    report.checks = [CheckResult("test", "pass", 1.0, "ok")]
    report.findings = [Finding("guardrails", HUMAN, "guardrail file changed", "ruff.toml")]
    body = build(repo.path, "s", report, "master")
    for heading in ("## Summary", "## Why", "## Commits (2", "## Verification", "## Review rounds", "## Deviations"):
        assert heading in body
    assert "_Not written" not in body and "Adds a." in body and "| 1 | x |" in body
    assert "### Needs a human" in body and "ruff.toml" in body
    assert "*(review fix)*" in body
    hashes = set(re.findall(r"`([0-9a-f]{7})`", body))
    known = {c.short for c in gitutil.commits(repo.path, "master", "HEAD")}
    assert hashes and hashes <= known


def test_a_stale_missing_or_wrong_base_report_is_said_plainly(repo):
    head = pr_repo(repo)
    stale = Report(mode="gate", sha="f" * 40, base="master")
    assert "verdict: stale" in build(repo.path, "s", stale, "master")
    assert "verdict: not run" in build(repo.path, "s", None, "master")
    wrong = Report(mode="gate", sha=head, base="HEAD", merge_base=head)
    wrong.checks = [CheckResult("test", "pass")]
    body = build(repo.path, "s", wrong, "master")
    assert "verdict: wrong base" in body and "PASS" not in body


def test_hashes_that_are_not_commits_are_marked(repo):
    head = pr_repo(repo)
    with open(os.path.join(repo.path, "design/s/build-log.md"), "a") as f:
        f.write("\n| 2 | see `deadbeef1` |\n")
    body = build(repo.path, "s", None, "master")
    assert "`deadbeef1` *(not a commit here)*" in body
    assert f"`{head[:7]}` *(not" not in body


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
