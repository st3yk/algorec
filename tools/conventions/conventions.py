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
MD_INLINE_LINK = re.compile(r"\]\(\s*(<[^>]*>|[^\s)]+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)")
MD_REF_DEF = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(<[^>]*>|\S+)")
MD_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
MD_ATX = re.compile(r"^ {0,3}#{1,6}(?:\s+(.*?))?(?:\s+#+)?\s*$")
MD_SETEXT = re.compile(r"^ {0,3}(=+|-+)\s*$")
CODE_SPAN = re.compile(r"(`+)(?:(?!\1).)+?\1")

RULES = {
    "no-comments": "AGENTS.md: no inline comments. Move the explanation into the module's docs/ page.",
    "no-docstrings": "AGENTS.md: no function or class docstrings. Explanations belong in docs/.",
    "no-bare-strings": "AGENTS.md: no inline comments, including string statements used as comments. Move it to docs/.",
    "module-docstring": "AGENTS.md: each Python file has one module docstring that points to its docs/ page.",
    "doc-ref-exists": "AGENTS.md: the module docstring must point to a real docs/ page. Fix the path or add the page.",
    "py-test-rule": "AGENTS.md: a new test file needs a py_test rule in tests/BUILD.bazel, not tagged manual.",
    "pytest-footer": 'docs/testing.md: test files end with `if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q"]))`.',
    "md-link": "AGENTS.md: docs change with code. A relative Markdown link doesn't resolve; fix the path or #anchor.",
    "syntax": "The file must parse as Python 3.12 (or Starlark, for BUILD files). Fix the syntax error.",
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


def _is_string_statement(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _docstrings(path: str, tree: ast.Module) -> list[Violation]:
    out = []
    docstrings: set[int] = set()
    if tree.body and _is_string_statement(tree.body[0]):
        docstrings.add(id(tree.body[0]))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and _is_string_statement(
            node.body[0]
        ):
            docstrings.add(id(node.body[0]))
            out.append(Violation(path, node.body[0].lineno, "no-docstrings", f"{node.name} has a docstring"))
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and _is_string_statement(node) and id(node) not in docstrings:
            out.append(Violation(path, node.lineno, "no-bare-strings", "a string statement that does nothing"))
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


def py_test_srcs(build_text: str) -> set[str]:
    try:
        tree = ast.parse(build_text)
    except SyntaxError:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "py_test"):
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        tags = kwargs.get("tags")
        if isinstance(tags, ast.List) and any(isinstance(t, ast.Constant) and t.value == "manual" for t in tags.elts):
            continue
        srcs = kwargs.get("srcs")
        if isinstance(srcs, ast.List):
            out |= {e.value for e in srcs.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return out


def check_test_rules(test_files: list[str], build_text: str) -> list[Violation]:
    declared = py_test_srcs(build_text)
    return [
        Violation(path, 1, "py-test-rule", f'no py_test with srcs = ["{path.rsplit("/", 1)[-1]}"]')
        for path in sorted(test_files)
        if path.rsplit("/", 1)[-1] not in declared
    ]


def github_slug(heading: str) -> str:
    text = re.sub(r"[`*]|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def _prose_lines(md_text: str) -> list[tuple[int, str]]:
    out = []
    fence: str | None = None
    for lineno, line in enumerate(md_text.splitlines(), 1):
        m = MD_FENCE.match(line)
        if fence is None and m:
            fence = m.group(1)
            continue
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip(fence[0] + " "):
                fence = None
            continue
        out.append((lineno, line))
    return out


def anchors(md_text: str) -> set[str]:
    seen: dict[str, int] = {}
    out = set()
    previous = ""
    for _, line in _prose_lines(md_text):
        heading = None
        atx = MD_ATX.match(line)
        if atx:
            heading = atx.group(1) or ""
        elif MD_SETEXT.match(line) and previous.strip() and not previous.lstrip().startswith(("|", "-", "*", ">")):
            heading = previous.strip()
        if heading is not None:
            slug = github_slug(heading)
            n = seen.get(slug, 0)
            seen[slug] = n + 1
            out.add(slug if n == 0 else f"{slug}-{n}")
        previous = line
    return out


def check_markdown(path: str, text: str, files: Mapping[str, str | None]) -> list[Violation]:
    out = []
    base = path.rsplit("/", 1)[0] if "/" in path else ""
    for lineno, line in _prose_lines(text):
        prose = CODE_SPAN.sub("", line)
        targets = MD_INLINE_LINK.findall(prose) + MD_REF_DEF.findall(prose)
        for raw in targets:
            target = raw[1:-1] if raw.startswith("<") else raw
            if re.match(r"[a-z][a-z0-9+.-]*:", target, re.I):
                continue
            file_part, _, anchor = target.partition("#")
            if file_part.startswith("/"):
                resolved = _normalize(file_part)
            else:
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
