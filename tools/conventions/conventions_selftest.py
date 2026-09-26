"""Self-tests for the convention checks: one violating fixture per rule. See docs/guardrails.md."""

import pytest

from tools.conventions.conventions import RULES, anchors, check_repo, github_slug

FOOTER = 'if __name__ == "__main__":\n    raise SystemExit(pytest.main([__file__, "-q"]))\n'
GOOD_MODULE = '"""A module. See docs/page.md."""\n\nX = "#not a comment"\n'
GOOD_TEST = "import pytest\n\n\ndef test_x():\n    assert True\n\n\n" + FOOTER
GOOD_BUILD = 'py_test(\n    name = "test_x",\n    srcs = ["test_x.py"],\n)\n'


def repo(**overrides: str | None) -> dict[str, str | None]:
    files: dict[str, str | None] = {
        "docs/page.md": "# Page\n\n## A `code` heading: yes\n\nSee [top](#page) and [README](../README.md).\n",
        "README.md": "[docs](docs/page.md#a-code-heading-yes)\n",
        "steerrec/mod.py": GOOD_MODULE,
        "steerrec/__init__.py": "",
        "tests/test_x.py": GOOD_TEST,
        "tests/BUILD.bazel": GOOD_BUILD,
        "proto/x.proto": None,
    }
    for key, value in overrides.items():
        files[key.replace("__", "/").replace("_DOT_", ".")] = value
    return files


def rules_of(files: dict[str, str | None]) -> list[str]:
    return [v.rule for v in check_repo(files)]


def test_a_clean_repo_has_no_violations():
    assert check_repo(repo()) == []


def test_inline_comment_is_rejected():
    files = repo(steerrec__mod_DOT_py=GOOD_MODULE + "Y = 1  # why\n")
    assert rules_of(files) == ["no-comments"]


def test_a_shebang_is_not_a_comment_but_a_later_one_is():
    text = '#!/usr/bin/env python3\n"""See docs/page.md."""\n# later\n'
    assert rules_of(repo(tools__run_DOT_py=text)) == ["no-comments"]


def test_function_and_class_docstrings_are_rejected():
    text = GOOD_MODULE + '\n\ndef f():\n    """Doc."""\n\n\nclass C:\n    """Doc."""\n'
    violations = check_repo(repo(steerrec__mod_DOT_py=text))
    assert [(v.rule, v.line) for v in violations] == [("no-docstrings", 7), ("no-docstrings", 11)]


def test_a_documented_package_needs_a_module_docstring():
    assert rules_of(repo(steerrec__mod_DOT_py="X = 1\n")) == ["module-docstring"]


def test_the_module_docstring_must_name_a_docs_page():
    assert rules_of(repo(tools__t_DOT_py='"""Does things."""\n')) == ["module-docstring"]


def test_a_missing_docs_page_is_rejected():
    text = '"""See docs/missing.md."""\n'
    violations = check_repo(repo(steerrec__mod_DOT_py=text))
    assert [(v.rule, v.detail) for v in violations] == [("doc-ref-exists", "docs/missing.md")]


def test_test_files_may_omit_the_module_docstring_and_empty_inits_are_exempt():
    assert check_repo(repo(tools____init___DOT_py="")) == []


def test_a_test_file_without_a_py_test_rule_is_rejected():
    files = repo(tests__test_y_DOT_py=GOOD_TEST)
    violations = check_repo(files)
    assert [(v.rule, v.path) for v in violations] == [("py-test-rule", "tests/test_y.py")]


def test_a_test_file_without_the_footer_is_rejected():
    files = repo(tests__test_x_DOT_py="def test_x():\n    assert True\n")
    assert rules_of(files) == ["pytest-footer"]


def test_a_broken_relative_link_is_rejected():
    files = repo(README_DOT_md="[x](docs/nope.md)\n")
    assert rules_of(files) == ["md-link"]


def test_a_broken_anchor_is_rejected_and_urls_and_code_are_ignored():
    text = "[x](docs/page.md#nope) [y](https://example.com/a.md) `[z](nope.md)`\n```\n[w](nope.md)\n```\n"
    violations = check_repo(repo(README_DOT_md=text))
    assert [v.detail for v in violations] == ["docs/page.md#nope (no heading #nope in docs/page.md)"]


def test_links_to_directories_and_non_text_files_resolve():
    assert check_repo(repo(README_DOT_md="[p](proto/x.proto) [d](steerrec/)\n")) == []


def test_a_syntax_error_is_reported_not_raised():
    assert rules_of(repo(steerrec__mod_DOT_py="def (:\n")) == ["syntax"]


@pytest.mark.parametrize(
    "heading, slug",
    [
        ("`assembler.py`: choosing and ordering the page", "assemblerpy-choosing-and-ordering-the-page"),
        ("Reading the seed-0 sweep", "reading-the-seed-0-sweep"),
        ("`test_model.py`: `Item` and `Registry`", "test_modelpy-item-and-registry"),
        ("U0 and bounds", "u0-and-bounds"),
    ],
)
def test_github_slugs(heading, slug):
    assert github_slug(heading) == slug


def test_duplicate_headings_get_numbered_anchors():
    assert anchors("# A\n## A\n```\n# B\n```\n") == {"a", "a-1"}


def test_every_rule_has_a_message_that_names_its_source():
    assert all(msg for msg in RULES.values())


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
