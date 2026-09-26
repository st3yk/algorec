"""Writes each pytest run's JUnit XML where Bazel asks (XML_OUTPUT_FILE), so tools/verify can
check that every test function ran and passed. See docs/guardrails.md."""

import os

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    path = os.environ.get("XML_OUTPUT_FILE")
    if path and not config.option.xmlpath:
        config.option.xmlpath = path
