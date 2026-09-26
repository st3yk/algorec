"""Writes each pytest run's JUnit XML where Bazel asks (XML_OUTPUT_FILE), so tools/verify can
check that every test function ran and passed. See docs/guardrails.md."""

import os

import pytest

RUNFILES_ROOT = "/_main/"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    path = os.environ.get("XML_OUTPUT_FILE")
    if path and not config.option.xmlpath:
        config.option.xmlpath = path


def defined_at(item: pytest.Item, root: str) -> str | None:
    function = getattr(item, "function", None)
    code = getattr(function, "__code__", None)
    if code is None:
        return None
    path = code.co_filename
    if RUNFILES_ROOT in path:
        path = path.rsplit(RUNFILES_ROOT, 1)[1]
    else:
        path = os.path.relpath(path, root)
    return f"{path}:{code.co_firstlineno}"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        where = defined_at(item, str(config.rootpath))
        if where:
            item.user_properties.append(("defined_at", where))
