"""Flags branch changes that weaken the checks judging the branch: edited guardrail files,
removed or loosened tests, skips, and a shrinking contract golden. See docs/guardrails.md."""

import ast
import fnmatch
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from tools.proto_compat.listing import breaking_changes, read_listing
from tools.verify_lib.findings import FAIL, HUMAN, Finding

GUARDRAIL_PATTERNS = (
    "tools/verify",
    "tools/pr_body",
    "tools/verify_drill",
    "tools/setup.sh",
    "tools/github/*",
    "tools/verify_lib/*",
    "tools/conventions/*",
    "tools/lint/*",
    "tools/proto_compat/*",
    "tools/hooks/*",
    "tools/githooks/*",
    "tools/agent/*",
    "ruff.toml",
    "mypy.ini",
    "pytest.ini",
    ".bazelrc",
    ".claude/settings.json",
    ".github/*",
    "CODEOWNERS",
)
GOLDEN = "proto/recommender.fields.golden"
SKIP_NAMES = ("pytest.mark.skip", "pytest.mark.skipif", "pytest.mark.xfail", "pytest.skip", "pytest.xfail")

Reader = Callable[[str], str | None]


def is_guardrail(path: str) -> bool:
    return any(path == p or fnmatch.fnmatchcase(path, p) for p in GUARDRAIL_PATTERNS)


def is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.endswith(".py") and (name.startswith("test_") or name.endswith(("_test.py", "_selftest.py")))


@dataclass
class TestFn:
    path: str
    asserts: Counter[str] = field(default_factory=Counter)
    decorators: list[str] = field(default_factory=list)
    skips: int = 0


def _test_functions(path: str, text: str) -> dict[str, TestFn]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test"):
            fn = TestFn(path, decorators=[ast.unparse(d) for d in node.decorator_list])
            for inner in ast.walk(node):
                if isinstance(inner, ast.Assert):
                    fn.asserts[ast.unparse(inner)] += 1
                elif isinstance(inner, ast.Call) and ast.unparse(inner.func) in ("pytest.raises", "pytest.approx"):
                    fn.asserts[ast.unparse(inner)] += 1
            fn.skips = sum(1 for d in node.decorator_list if _is_skip(d))
            fn.skips += sum(1 for inner in ast.walk(node) if isinstance(inner, ast.Call) and _is_skip(inner.func))
            out[node.name] = fn
    return out


def _is_skip(node: ast.expr) -> bool:
    target = node.func if isinstance(node, ast.Call) else node
    return ast.unparse(target) in SKIP_NAMES


def _group(path: str) -> str:
    parts = path.split("/")
    return "/".join(parts[:2]) + "/" if len(parts) > 2 else path


def _py_tests(text: str) -> dict[str, bool]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "py_test":
            kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            name = kwargs.get("name")
            if isinstance(name, ast.Constant) and isinstance(name.value, str):
                tags = kwargs.get("tags")
                manual = isinstance(tags, ast.List) and any(
                    isinstance(t, ast.Constant) and t.value == "manual" for t in tags.elts
                )
                out[name.value] = manual
    return out


def _collect(paths: list[str], read: Reader) -> tuple[dict[str, list[TestFn]], dict[str, bool]]:
    fns: dict[str, list[TestFn]] = {}
    rules: dict[str, bool] = {}
    for path in paths:
        text = read(path)
        if text is None:
            continue
        if is_test_file(path):
            for name, fn in _test_functions(path, text).items():
                fns.setdefault(name, []).append(fn)
        elif path.endswith("BUILD.bazel"):
            package = path.rsplit("/", 1)[0] if "/" in path else ""
            for name, manual in _py_tests(text).items():
                rules[f"//{package}:{name}"] = manual
    return fns, rules


def check_guardrails(
    changed: list[str], base_files: list[str], head_files: list[str], read_base: Reader, read_head: Reader
) -> list[Finding]:
    groups: dict[str, list[str]] = {}
    for path in changed:
        if is_guardrail(path):
            groups.setdefault(_group(path), []).append(path)
    out = [
        Finding(
            "guardrails",
            HUMAN,
            f"guardrail change: {', '.join(p.rsplit('/', 1)[-1] for p in paths[:6])}"
            + (f" and {len(paths) - 6} more" if len(paths) > 6 else ""),
            group,
        )
        for group, paths in sorted(groups.items())
    ]
    out += _check_tests(changed, base_files, head_files, read_base, read_head)
    out += _check_golden(read_base(GOLDEN), read_head(GOLDEN))
    return out


def _check_tests(
    changed: list[str], base_files: list[str], head_files: list[str], read_base: Reader, read_head: Reader
) -> list[Finding]:
    relevant = {p for p in changed if is_test_file(p) or p.endswith("BUILD.bazel")}
    if not relevant:
        return []
    base_fns, base_rules = _collect([p for p in base_files if is_test_file(p) or p.endswith("BUILD.bazel")], read_base)
    head_fns, head_rules = _collect([p for p in head_files if is_test_file(p) or p.endswith("BUILD.bazel")], read_head)
    out = []
    for name, olds in sorted(base_fns.items()):
        if not any(fn.path in relevant for fn in olds) and name in head_fns:
            continue
        news = head_fns.get(name)
        if not news:
            out.append(Finding("guardrails", HUMAN, f"test `{name}` was removed or renamed", olds[0].path))
            continue
        old_asserts = sum((fn.asserts for fn in olds), Counter())
        new_asserts = sum((fn.asserts for fn in news), Counter())
        for text in sorted((old_asserts - new_asserts).elements())[:3]:
            out.append(Finding("guardrails", HUMAN, f"`{name}` lost or changed a check: `{text[:100]}`", news[0].path))
        old_decorators = Counter(d for fn in olds for d in fn.decorators)
        new_decorators = Counter(d for fn in news for d in fn.decorators)
        for text in sorted((old_decorators - new_decorators).elements())[:3]:
            out.append(Finding("guardrails", HUMAN, f"`{name}` lost or changed `@{text[:100]}`", news[0].path))
        if sum(fn.skips for fn in news) > sum(fn.skips for fn in olds):
            out.append(Finding("guardrails", HUMAN, f"`{name}` gained a skip or xfail", news[0].path))
    for name, news in sorted(head_fns.items()):
        if name not in base_fns and any(fn.skips for fn in news):
            out.append(Finding("guardrails", HUMAN, f"new test `{name}` is skipped or xfailed", news[0].path))
    for label, manual in sorted(base_rules.items()):
        if label not in head_rules:
            out.append(Finding("guardrails", HUMAN, "py_test rule was removed", label))
        elif head_rules[label] and not manual:
            out.append(Finding("guardrails", HUMAN, "py_test rule is now tagged manual, so //... skips it", label))
    return out


def _check_golden(base: str | None, head: str | None) -> list[Finding]:
    if base is None:
        return []
    if head is None:
        return [Finding("guardrails", FAIL, "the contract golden was deleted", GOLDEN)]
    old, new = read_listing(base), read_listing(head)
    broken = breaking_changes(old, new)
    out = [Finding("guardrails", FAIL, f"breaking against the base contract: {b}", GOLDEN) for b in broken]
    removed = sorted(set(old) - set(new))
    if removed and not broken:
        out.append(
            Finding("guardrails", HUMAN, f"{len(removed)} line(s) removed from the golden: {removed[0]}", GOLDEN)
        )
    return out
