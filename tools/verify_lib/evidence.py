"""Runtime evidence: every test function in the head's test files must have a passed JUnit
result from the gate's test run, recorded as coming from that very `def`. See
docs/guardrails.md."""

import ast
import os
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass

from tools.verify_lib.findings import FAIL, HUMAN, Finding
from tools.verify_lib.guardrails import is_test_file

PARAMS = re.compile(r"\[.*\]$")
SKIP_TEXT = re.compile(r"\b(skip|skipif|xfail|importorskip)\b")

Reader = Callable[[str], str | None]


@dataclass(frozen=True)
class Expected:
    defined_at: str
    skip_in_base: bool = False


@dataclass(frozen=True)
class Result:
    outcome: str
    defined_at: str


def _tests(path: str, text: str) -> dict[tuple[str, str], tuple[int, ast.AST]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    module = path[:-3].replace("/", ".")
    out: dict[tuple[str, str], tuple[int, ast.AST]] = {}

    def first_line(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
        return min([node.lineno, *(d.lineno for d in node.decorator_list)])

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test"):
            out[(module, node.name)] = (first_line(node), node)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for inner in node.body:
                if isinstance(inner, ast.FunctionDef | ast.AsyncFunctionDef) and inner.name.startswith("test"):
                    out[(f"{module}.{node.name}", inner.name)] = (first_line(inner), inner)
    return out


def _module_skips(text: str) -> bool:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    return any(
        SKIP_TEXT.search(ast.unparse(node))
        for node in tree.body
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Import | ast.ImportFrom)
    )


def required_tests(
    paths: list[str], read_head: Reader, read_base: Reader | None = None
) -> dict[tuple[str, str], Expected]:
    out: dict[tuple[str, str], Expected] = {}
    for path in paths:
        if not is_test_file(path) or path.rsplit("/", 1)[-1] == "conftest.py":
            continue
        text = read_head(path)
        if text is None:
            continue
        base_text = read_base(path) if read_base else None
        base_tests = _tests(path, base_text) if base_text else {}
        base_module_skip = bool(base_text) and _module_skips(base_text or "")
        for key, (line, _) in _tests(path, text).items():
            base = base_tests.get(key)
            skipped = base_module_skip or (base is not None and bool(SKIP_TEXT.search(ast.unparse(base[1]))))
            out[key] = Expected(f"{path}:{line}", skipped)
    return out


def collect_results(testlogs: str) -> dict[tuple[str, str], list[Result]]:
    results: dict[tuple[str, str], list[Result]] = {}
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
                where = ""
                for prop in case.iter("property"):
                    if prop.get("name") == "defined_at":
                        where = prop.get("value", "")
                results.setdefault(key, []).append(Result(outcome, where))
    return results


def check_evidence(
    required: dict[tuple[str, str], Expected], results: dict[tuple[str, str], list[Result]]
) -> list[Finding]:
    out = []
    for (module, name), expected in sorted(required.items()):
        where = expected.defined_at.rsplit(":", 1)[0]
        cases = results.get((module, name), [])
        if not cases:
            out.append(Finding("evidence", FAIL, f"`{name}` never ran in any py_test target", where))
            continue
        if not any(c.defined_at for c in cases):
            message = f"`{name}` ran without a definition record: is //:conftest.py in its py_test's data?"
            out.append(Finding("evidence", FAIL, message, where))
            continue
        ours = [c for c in cases if c.defined_at == expected.defined_at]
        if not ours:
            ran = sorted({c.defined_at for c in cases if c.defined_at})[0]
            message = f"the `{name}` that ran came from {ran}, not the def at {expected.defined_at}"
            out.append(Finding("evidence", FAIL, message, where))
            continue
        outcomes = {c.outcome for c in ours}
        if outcomes <= {"skipped"}:
            if not expected.skip_in_base:
                out.append(Finding("evidence", HUMAN, f"`{name}` is newly skipped: every run of it was skipped", where))
        elif "passed" not in outcomes:
            message = f"`{name}` ran but never passed ({', '.join(sorted(outcomes))})"
            out.append(Finding("evidence", FAIL, message, where))
        elif "skipped" in outcomes and not expected.skip_in_base:
            out.append(Finding("evidence", HUMAN, f"`{name}` is newly skipped in some runs", where))
    return out
