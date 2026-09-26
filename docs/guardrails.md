# Guardrails: how a change is judged

Every check that decides whether a change is good lives in this repository and
runs through Bazel. Agents and humans run the same commands and get the same
answer.

## Branch checks

These checks look at the commits between the merge-base and HEAD. They live in
`tools/verify_lib/`.


| Check | FAIL | NEEDS_HUMAN |
|---|---|---|
| `commits` | A subject that isn't `type(scope): summary` (types: feat, fix, test, refactor, build, chore, docs, perf, style, ci, revert), starts with a capital, or is over 72 characters; a WIP or `fixup!` commit; a merge commit; a lock-file change mixed with other files. | |
| `docs` | A `feat`, `fix`, `perf` or `revert` commit that changes a source in `tools/verify_lib/docs_map.json` without changing its docs page in the same commit. | The same, with a `Docs-Unchanged: <reason>` trailer. The reason goes into the report. |
| `guardrails` | The contract golden breaks against the base's golden, or was deleted. | A guardrail file changed (`tools/verify*`, `tools/verify_lib/`, `tools/conventions/`, `tools/lint/`, `tools/proto_compat/`, `tools/hooks/`, `tools/githooks/`, `tools/agent/`, `ruff.toml`, `mypy.ini`, `pytest.ini`, `.bazelrc`, `.claude/settings.json`, `.github/`, `CODEOWNERS`). A test function removed or renamed; an `assert`, `pytest.raises` or `pytest.approx` removed or changed; a decorator such as `parametrize` removed or changed; a skip or xfail added; a `py_test` rule removed or tagged `manual`; a line removed from the golden. |

Test functions are compared by name across all test files, and asserts by
their normalized source, so moving a test or reformatting an assert isn't a
finding. `style`, `refactor`, `test`, `build`, `chore`, `docs` and `ci`
commits claim no behavior change, so `docs` doesn't apply to them; the
reviewer checks that claim.

`tools/verify_lib/` runs under the system Python (3.10 or newer), so it uses
only the standard library, and ruff checks it with `target-version = py310`.
Its rules are tested by `//tools/verify_lib:selftest` on scratch git
repositories.

## Lint and format

| Target | What it checks |
|---|---|
| `//tools/lint:ruff_check` | `ruff check` over `steerrec/`, `tests/` and `tools/`, with the rules in `ruff.toml`. |
| `//tools/lint:ruff_format_check` | `ruff format --check`: the code is formatted as ruff would format it. |
| `bazel run //tools/lint:fix` | Applies ruff's safe fixes and formatting to the whole repository. |
| `bazel run //tools/lint:ruff -- <args>` | Runs the locked ruff binary on anything, from the repo root. |

`ruff.toml` selects `E,F,W,I,B,UP,ERA`, with three rules switched off:
- `E501`, because the formatter owns line length (120);
- `E731`, because assigned lambdas are used in the core;
- `B905`, because `zip(strict=)` would add runtime checks to the assembler.

Because inline comments aren't allowed, there is no `# noqa`. Exceptions go into
`[lint.per-file-ignores]` in `ruff.toml`.

The ruff binary comes from the locked PyPI wheel (`@pypi//ruff:data`), so its
version is pinned like any other dependency.

## Types

`//tools/lint:mypy` runs mypy over `steerrec/` and `tools/` with `mypy.ini`.
Every function in `steerrec/` must be fully annotated (`disallow_untyped_defs`).
Tests aren't type-checked. mypy sees the real numpy, protobuf (via
`types-protobuf`) and pytest types; only scipy, which ships no stubs for
`scipy.optimize`, is treated as untyped.

## Conventions

`//tools/conventions:test` checks the AGENTS.md rules that a machine can check,
over every file in the repository (`//:repo_files`):

| Rule | What fails |
|---|---|
| `no-comments` | A `#` comment in `steerrec/`, `tests/` or `tools/` Python files. A shebang on line 1 is allowed. |
| `no-docstrings` | A function or class docstring, including an empty one. |
| `no-bare-strings` | A string statement anywhere but the module docstring: a second module string, or a string used as a comment inside code. |
| `module-docstring` | A file in `steerrec/` or `tools/` with no module docstring, or one that names no `docs/` page. Test files and empty `__init__.py` files are exempt, since `docs/testing.md` documents the tests. |
| `doc-ref-exists` | A module docstring names a `docs/…` page (or `NORTH_STAR.md`, `BUILDING.md`, `AGENTS.md`) that doesn't exist. |
| `py-test-rule` | A `tests/test_*.py` file that isn't in the `srcs` of a `py_test` in `tests/BUILD.bazel`, or only in one tagged `manual`. The BUILD file is parsed, not searched, so a `py_library` or a commented-out rule doesn't count. |
| `pytest-footer` | A test file that doesn't end with the pytest footer. |
| `md-link` | A relative link or image to a missing file, or to a `#anchor` that no heading produces. It covers inline links (with titles and `<…>` destinations), images, reference definitions, and repo-root paths (`/docs/…`). Anchors follow GitHub's slug rules, for ATX headings (closing `#`s allowed) and setext headings. Links in code spans and fenced blocks are ignored. Link text that spans lines is not checked. |

Every failure prints the file, the line, and the rule it breaks. The rules are
tested by `//tools/conventions:selftest`, with one violating fixture per rule.

A new Bazel package must add its `all_files` filegroup to `//:repo_files`, and
its `py_srcs` to `//tools:py_srcs` if it's under `tools/`. Otherwise its files
aren't checked, and links to them don't resolve.

## Service contract compatibility

`//tools/proto_compat:test` flattens the descriptor set of
`//proto:recommender_proto` into one line per file syntax, service, RPC, message,
oneof, field (with its JSON name and oneof), enum value and reservation. It compares that listing with `proto/recommender.fields.golden`.

| Change | Result |
|---|---|
| A field or enum value moved to another number | Fails (breaking). |
| A field removed without `reserved` for its number | Fails (breaking). |
| A reserved number or name reused, or a reservation dropped | Fails (breaking). |
| A field's name, label or type changed | Fails (breaking). |
| A message or enum removed | Fails (breaking). |
| An RPC removed, or its request, response or streaming changed; a service removed | Fails (breaking). |
| A field moved into or out of a oneof, or its JSON name changed | Fails (breaking). |
| The file's syntax or edition changed | Fails (breaking). |
| A new RPC | Compatible (golden update needed). |
| A new field, value, message or reservation | Fails until the golden is updated: `bazel run //tools/proto_compat:update_golden`. |

`update_golden` refuses to write when the change is breaking, so the golden can
only grow. Don't edit the golden by hand.
