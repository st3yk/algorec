# Guardrails: how a change is judged

Every check that decides whether a change is good lives in this repository and
runs through Bazel. Agents and humans run the same commands and get the same
answer.

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
Tests aren't type-checked.
