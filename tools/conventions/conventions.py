"""Checks the AGENTS.md conventions that a machine can check. See docs/guardrails.md."""

import ast
import io
import re
import tokenize
from collections.abc import Callable, Mapping
from dataclasses import dataclass

CODE_DIRS = ("steerrec/", "tests/", "tools/")
DOCUMENTED_DIRS = ("steerrec/", "tools/")
PYTEST_FOOTER = ('if __name__ == "__main__":', '    raise SystemExit(pytest.main([__file__, "-q"]))')
DOC_REF = re.compile(r"(?<![\w/])((?:docs/[\w./-]+\.md)|NORTH_STAR\.md|BUILDING\.md|AGENTS\.md)")
MD_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
PY_TEST_SRC = re.compile(r'srcs\s*=\s*\[\s*"(test_[\w]+\.py)"')

RULES = {
    "no-comments": "AGENTS.md: no inline comments. Move the explanation into the module's docs/ page.",
    "no-docstrings": "AGENTS.md: no function or class docstrings. Explanations belong in docs/.",
    "module-docstring": "AGENTS.md: each Python file has one module docstring that points to its docs/ page.",
    "doc-ref-exists": "The module docstring points to a docs page that doesn't exist. Fix the path or add the page.",
    "py-test-rule": "AGENTS.md: a new test file needs a py_test rule in tests/BUILD.bazel.",
    "pytest-footer": 'docs/testing.md: test files end with `if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q"]))`.',
    "md-link": "A relative Markdown link doesn't resolve. Fix the path or the #anchor.",
    "syntax": "The file doesn't parse.",
}


@dataclass(frozen=True, order=True)
class Violation:
    path: str
    line: int
    rule: str
    detail: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.detail}\n    {RULES[self.rule]}"


def check_python(path: str, text: str, exists: Callable[[str], bool]) -> list[Violation]:
    if not path.startswith(CODE_DIRS) or not path.endswith(".py"):
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [Violation(path, e.lineno or 1, "syntax", str(e.msg))]
    out = _comments(path, text)
    out += _docstrings(path, tree)
    out += _module_docstring(path, text, tree, exists)
    if path.startswith("tests/") and path.rsplit("/", 1)[-1].startswith("test_"):
        out += _footer(path, text)
    return out


def _comments(path: str, text: str) -> list[Violation]:
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT and not (tok.start[0] == 1 and tok.string.startswith("#!")):
            out.append(Violation(path, tok.start[0], "no-comments", tok.string[:60]))
    return out


def _docstrings(path: str, tree: ast.Module) -> list[Violation]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and ast.get_docstring(node):
            out.append(Violation(path, node.body[0].lineno, "no-docstrings", f"{node.name} has a docstring"))
    return out


def _module_docstring(path: str, text: str, tree: ast.Module, exists: Callable[[str], bool]) -> list[Violation]:
    doc = ast.get_docstring(tree)
    if doc is None:
        if path.startswith(DOCUMENTED_DIRS) and text.strip():
            return [Violation(path, 1, "module-docstring", "no module docstring")]
        return []
    refs = DOC_REF.findall(doc)
    if path.startswith(DOCUMENTED_DIRS) and not refs:
        return [Violation(path, 1, "module-docstring", "the module docstring doesn't name a docs/ page")]
    return [Violation(path, 1, "doc-ref-exists", ref) for ref in refs if not exists(ref)]


def _footer(path: str, text: str) -> list[Violation]:
    lines = [line for line in text.rstrip().splitlines() if line.strip()]
    if tuple(lines[-2:]) != PYTEST_FOOTER:
        return [Violation(path, len(text.splitlines()), "pytest-footer", "missing or different footer")]
    return []


def check_test_rules(test_files: list[str], build_text: str) -> list[Violation]:
    declared = set(PY_TEST_SRC.findall(build_text))
    return [
        Violation(path, 1, "py-test-rule", f'no py_test with srcs = ["{path.rsplit("/", 1)[-1]}"]')
        for path in sorted(test_files)
        if path.rsplit("/", 1)[-1] not in declared
    ]


def github_slug(heading: str) -> str:
    text = re.sub(r"[`*]|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(md_text: str) -> set[str]:
    seen: dict[str, int] = {}
    out = set()
    in_fence = False
    for line in md_text.splitlines():
        if line.startswith("```") or line.startswith("~~~"):
            in_fence = not in_fence
        if in_fence:
            continue
        m = re.match(r"#{1,6}\s+(.*)", line)
        if m:
            slug = github_slug(m.group(1))
            n = seen.get(slug, 0)
            seen[slug] = n + 1
            out.add(slug if n == 0 else f"{slug}-{n}")
    return out


def check_markdown(path: str, text: str, files: Mapping[str, str | None]) -> list[Violation]:
    out = []
    in_fence = False
    base = path.rsplit("/", 1)[0] if "/" in path else ""
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.startswith("```") or line.startswith("~~~"):
            in_fence = not in_fence
        if in_fence:
            continue
        for target in MD_LINK.findall(re.sub(r"`[^`]*`", "", line)):
            if re.match(r"[a-z]+:", target):
                continue
            file_part, _, anchor = target.partition("#")
            resolved = _normalize(f"{base}/{file_part}" if base and file_part else file_part or path)
            if resolved not in files and not any(f.startswith(resolved.rstrip("/") + "/") for f in files):
                out.append(Violation(path, lineno, "md-link", f"{target} (no file {resolved})"))
                continue
            content = files.get(resolved)
            if anchor and resolved.endswith(".md") and content is not None and anchor not in anchors(content):
                out.append(Violation(path, lineno, "md-link", f"{target} (no heading #{anchor} in {resolved})"))
    return out


def _normalize(path: str) -> str:
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def check_repo(files: Mapping[str, str | None]) -> list[Violation]:
    out: list[Violation] = []
    for path, text in files.items():
        if text is None:
            continue
        if path.endswith(".py"):
            out += check_python(path, text, lambda ref: ref in files)
        elif path.endswith(".md"):
            out += check_markdown(path, text, files)
    tests = [p for p in files if re.fullmatch(r"tests/test_\w+\.py", p)]
    out += check_test_rules(tests, files.get("tests/BUILD.bazel") or "")
    return sorted(out)
