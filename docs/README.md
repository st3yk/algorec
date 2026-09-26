# steerrec documentation

These pages describe **what is built**. For where the project is heading, see
[`NORTH_STAR.md`](../NORTH_STAR.md).

| Page | Read it for |
|---|---|
| [concepts.md](concepts.md) | The steering math: `p`, `q`, shares, U0, one-sided bounds, guarantees, glossary. Read this first. |
| [code/items-and-registry.md](code/items-and-registry.md) | `Item`, `Dimension`, `Registry`, control validation. |
| [code/targets.md](code/targets.md) | U0, exclusive mass, `Bound`, `compute_bounds`. |
| [code/assembler.md](code/assembler.md) | The staged ILP, fallbacks, time budget, greedy, ordering, shortfall. |
| [code/synthetic-and-demo.md](code/synthetic-and-demo.md) | The synthetic catalog and the demo CLI. |
| [service-contract.md](service-contract.md) | The gRPC contract in `proto/`, field by field, and what backs it today. |
| [testing.md](testing.md) | What each test file establishes, and test conventions. |
| [guardrails.md](guardrails.md) | The checks that judge a change: lint, types, conventions, and how to run them. |
| [decisions.md](decisions.md) | Non-obvious choices, findings from building, rejected alternatives. |

## Architecture of the built part

```
             synthetic.make_catalog          (stand-in for scoring + ranking)
                        │ list[Item]
                        ▼
control ──► assembler.assemble ──────────────────────────────────────► Page
                │
                ├─ targets.dedupe_pool, sort by (-p, video_id)
                ├─ registry.check_scores
                ├─ targets.unsteered_page ─► U0
                ├─ targets.compute_bounds ─► list[Bound]     (uses registry.validate_control)
                ├─ _solve_ilp: stage 0 ─► stage 1 ─► stage 2  (scipy milp / HiGHS)
                │     └─ on failure: _swap_greedy, _better_page
                ├─ _order     (spread steered items)
                └─ _shortfalls
```

Module dependencies run one way: `items` ← `registry` ← `targets` ← `assembler`,
and `synthetic` and `demo` sit on top. Nothing imports `demo`.

## Bazel targets

| Target | What |
|---|---|
| `//steerrec:items`, `:registry`, `:targets`, `:assembler`, `:synthetic` | One `py_library` per module. |
| `//steerrec:demo` | The CLI (`py_binary`). `:demo_lib` is the same code as a library for tests. |
| `//proto:recommender_proto` | The service contract (`proto_library`). |
| `//tests:test_*` | One `py_test` per test file. |
| `//:requirements`, `//:requirements.update`, `//:requirements_test` | The PyPI lock file and its freshness check. |
| `//tools/lint:*` | Lint, format and type checks, and `:fix` (see [guardrails.md](guardrails.md)). |

For setup and dependency management, see [`BUILDING.md`](../BUILDING.md).

## Keeping these docs true

The code has no inline comments or function docstrings. Each module has a short
docstring that points here. When you change behavior, update the matching page
in the same commit.
