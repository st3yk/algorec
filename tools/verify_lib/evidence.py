"""Runtime evidence: every test function in the head's test files must have at least one
passed JUnit result from the gate's test run. See docs/guardrails.md."""

import ast
import os
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable

from tools.verify_lib.findings import FAIL, Finding
from tools.verify_lib.guardrails import is_test_file

PARAMS = re.compile(r"\[.*\]$")


def required_tests(paths: list[str], read: Callable[[str], str | None]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for path in paths:
        if not is_test_file(path) or path.rsplit("/", 1)[-1] == "conftest.py":
            continue
        text = read(path)
        if text is None:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        module = path[:-3].replace("/", ".")
        for node in tree.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test"):
                out.add((module, node.name))
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                for inner in node.body:
                    if isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef) and inner.name.startswith("test"):
                        out.add((f"{module}.{node.name}", inner.name))
    return out


def collect_results(testlogs: str) -> dict[tuple[str, str], set[str]]:
    results: dict[tuple[str, str], set[str]] = {}
    root = os.path.realpath(testlogs)
    for dirpath, _, names in os.walk(root, followlinks=True):
        for name in names:
            if name != "test.xml":
                continue
            try:
                tree = ET.parse(os.path.join(dirpath, name))
            except (ET.ParseError, OSError):
                continue
            for case in tree.iter("testcase"):
                key = (case.get("classname", ""), PARAMS.sub("", case.get("name", "")))
                outcome = "passed"
                for child in case:
                    if child.tag in ("skipped", "failure", "error"):
                        outcome = child.tag
                results.setdefault(key, set()).add(outcome)
    return results


def check_evidence(required: set[tuple[str, str]], results: dict[tuple[str, str], set[str]]) -> list[Finding]:
    out = []
    for module, name in sorted(required):
        outcomes = results.get((module, name), set())
        where = f"{module.replace('.', '/')}.py"
        if not outcomes:
            out.append(Finding("evidence", FAIL, f"`{name}` never ran in any py_test target", where))
        elif "passed" not in outcomes:
            out.append(
                Finding("evidence", FAIL, f"`{name}` ran but never passed ({', '.join(sorted(outcomes))})", where)
            )
        elif "skipped" in outcomes:
            out.append(Finding("evidence", FAIL, f"`{name}` was skipped in some runs", where))
    return out
