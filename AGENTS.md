# Guide for agents working in this repo

steerrec is a steerable short-video recommender. The user moves a
"Fun ↔ Learn" control, and the feed's content mix follows it while staying
relevant. Today only the steering core is built, and it runs on synthetic items.

## Read before changing anything

1. [`NORTH_STAR.md`](NORTH_STAR.md): the product promises that must hold, and
   what is built vs. planned.
2. [`docs/concepts.md`](docs/concepts.md): the vocabulary (`p`, `q`, U0,
   shares, one-sided bounds).
3. The `docs/code/*.md` page for the module you are touching.

## The service contract

- [`proto/steerrec/v1/recommender.proto`](proto/steerrec/v1/recommender.proto)
  is the contract between the backend and the recommender.
- The Bazel target is `//proto:recommender_proto`, and the import path is
  `steerrec/v1/recommender.proto`.
- Field meanings and what backs them today are in
  [`docs/service-contract.md`](docs/service-contract.md).
- Never renumber or reuse a field number.

## Commands

```sh
tools/verify --fast                # before every commit: fast tests and coverage
tools/verify                       # before every push: the gate (PASS/FAIL/NEEDS_HUMAN/ERROR)
tools/pr_body <slug>               # PR description from the gate report, git and design/<slug>/
bazel build //...
bazel test //...
bazel run //steerrec:demo -- --sweep-only
bazel run //:requirements.update   # after editing requirements.in
bazel run //tools/lint:fix         # apply ruff fixes and formatting
bazel run //tools/proto_compat:update_golden   # after adding proto fields
```

There is no local venv. Always run Python through Bazel: the system Python's
scipy has no `milp`.

## Agent workflow

Skills (`/algo-design-loop`, `/algo-build-loop`) read this section to find the
repository's contract. `tools/verify`'s exit code is the only definition of
"good": never summarize a verdict from memory, paste the report.

- verify-fast: `tools/verify --fast`
- verify: `tools/verify --base origin/master`
- verify-deep: `tools/verify --deep --base origin/master`
- design-dir: `design/<slug>/` (plan.md, build-log.md, review-log.md, summary.md)
- start-build: `tools/agent/start_build.sh <slug>`
- pr-body: `tools/pr_body <slug>`
- setup: `tools/setup.sh` (enables the git hooks)

Verdicts: 0 `PASS`, 1 `FAIL`, 2 `NEEDS_HUMAN`, 3 `ERROR`. A PR may be marked
ready only on `PASS` at its head commit. `NEEDS_HUMAN` stays a draft with the
reasons at the top. Agents never merge. `design/` holds plans and logs of work
in flight; `docs/` describes what is built.

## Code map

| Path | What |
|---|---|
| `steerrec/items.py` | `Item(video_id, creator_id, p, q)` |
| `steerrec/registry.py` | Dimensions, control validation, `single_slider` |
| `steerrec/targets.py` | U0, exclusive mass, one-sided bounds |
| `steerrec/assembler.py` | Staged ILP, fallback, ordering, shortfall |
| `steerrec/synthetic.py` | Seeded fake catalog |
| `steerrec/demo.py` | CLI |
| `proto/` | Service contract |
| `tools/` | Guardrails: lint, conventions, verify (see `docs/guardrails.md`) |
| `tests/` | One `py_test` per file (see `docs/testing.md`) |
| `docs/` | Documentation of what is built |

## Conventions

- **No inline comments and no function or class docstrings.** Each Python file
  has one module docstring: a short description that points to its `docs/`
  page. Explanations belong in `docs/`.
- **Docs change with code.** A behavior change updates the matching `docs/`
  page in the same commit. A non-obvious choice goes into `docs/decisions.md`.
- **Keep the promises in `NORTH_STAR.md`.** In particular, a steered page is
  never on the wrong side of neutral, and a missed bound is always reported as a
  `Shortfall`.
- **Tests**: a bug fix comes with a test that fails without it. Prefer property
  tests over seeds, and check the optimizer against brute force on small pools.
  A new test file needs a `py_test` rule in `tests/BUILD.bazel`.
- **Dependencies**: add to `requirements.in`, re-lock, and reference as
  `@pypi//<name>`.
- **Commits**: Conventional Commits (`feat(assembler): ...`,
  `fix(registry): ...`, `docs: ...`), one logical change each.
