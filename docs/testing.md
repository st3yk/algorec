# Testing

```sh
bazel test //...                          # everything (results are cached)
bazel test //... --nocache_test_results   # force a re-run
bazel test //tests:test_assembler         # one file
```

Each file in `tests/` is its own `py_test` target and ends with
`if __name__ == "__main__": raise SystemExit(pytest.main([__file__, "-q"]))`,
because Bazel runs the file directly. When you add a test file, add a `py_test`
rule to `tests/BUILD.bazel` with the `//steerrec:*` and `@pypi//*` deps it
imports.

## What each file establishes

### `test_toolchain.py`
- The interpreter is rules_python's hermetic 3.12, not a system Python. It
  follows `sys.executable`'s symlink hops to the toolchain repo.
- scipy has `milp`, which needs scipy ≥ 1.9. The system Python has 1.8, which is
  why the hermetic toolchain is needed.

### `test_model.py`: `Item` and `Registry`
- Probabilities are validated. A missing score reads as 0.
- `Dimension` end points and priority are validated.
- Controls are clamped. Unknown dimensions, NaN, strings and bools are
  rejected. numpy scalars are accepted.
- Scores are read-only, and a later change to the caller's dict does not leak
  in. Items are hashable.

### `test_targets.py`: U0 and bounds
- U0 is the top-P by relevance with one item per creator. Ties are
  deterministic. It matches a brute-force definition. It handles small and
  empty pools.
- Identical duplicates are kept once. Conflicting duplicates raise, whichever
  copy comes first.
- The exclusive-mass formula, including "a dimension is not exclusive of
  itself".
- Targets never point against the slider, tighten with |s|, interpolate
  linearly, reach the end points at |s| = 1, and stay at U0's value when U0 is
  already past the end point.
- Shares are divided by the page size, not the pool size. The order of bounds
  follows the registry. N dimensions use the same formulas.

### `test_assembler.py`: the page
- **s = 0 gives exactly U0.**
- **Ordering**: 3 steered items of 10 land at 2, 5, 8. For every count, the
  positions are distinct and spread with no bunching at either end.
- **Always feasible**: degenerate pools (empty, one creator, no supply of a
  kind) never raise and report shortfall. An all-light pool at max learning
  still fills the page.
- **Bounds**: met whenever supply makes them feasible, and otherwise the exact
  gap is reported.
- **Stage 2**: the objective is `q(q − 0.5)`. It prefers clear items within δ
  but not beyond. Clarity ties go to relevance regardless of pool order.
- **Order independence**: the page doesn't depend on pool order, even with many
  exactly tied scores.
- **Never below neutral**: a minimal hand-built case, a scaled-up case, and a
  30-seed property over ILP, fallback and shortfall pages. The scaled-up case
  fails on 30 of 30 seeds if either the ILP or the greedy guard is removed.
- **Creator-limited pool**: the page stays full. This is a regression test.
  Stage 0 used to prefer dropping an item (cardinality slack 3.0) over U0's bound
  slack (4.0), and served 5 of 6 items. This is why the `Σx ≥ |U0|` row exists.
- **Optimality**: on small pools, the ILP matches brute-force enumeration of
  every creator-respecting, not-worse-than-neutral page for all three stages.
- **Monotonicity**: the mean realized share is monotone across slider points,
  and the full slider moves the mean well past neutral.
- **Time and failures**: a `ScriptedSolver` makes any stage hit the limit (with
  or without an incumbent) or raise.
  - A stage-1 failure serves a relevant page, not stage 0's relevance-blind one.
  - When greedy stalls, stage 0's page wins.
  - Only stage 0 uses a zero MIP gap.
  - The budget includes model building and is shared across stages.
  - `time_limit_s` must be finite and ≥ 0.
  - A 300-item pool is solved to optimality given a generous 60 s budget. This
    is a regression test: at 50 ms per stage, the page's mean p was 0.75
    instead of 0.85.
  - The 2 s default budget is enough for the same pool. This test depends on
    the machine's speed.
- **Fallback**: it respects the creator rule and reports what it can't meet. The
  incremental implementation matches a naive reference. It meets the bounds
  when an easy swap exists.

### `test_synthetic.py`: the synthetic catalog and success criterion 1
- The catalog is deterministic per seed, with the intended kind mix and a light
  bias in `p`.
- **Criterion 1**: over 12 synthetic users and 11 slider points, on pages without
  shortfall, the mean pushed-up total share never falls, and the mean
  pushed-down pure share never rises, by more than 0.03 between neighbouring
  points.
  - It runs with two registries. With the default end points, the left-side
    bounds never bite on these users (see the
    [demo notes](code/synthetic-and-demo.md#reading-the-seed-0-sweep)), so a
    `left_active` registry (`t_min_edu` = 0.01, `t_max_light` = 0.9) exercises
    that side.

### `test_demo.py`
- The CLI runs, prints pages and 11 sweep rows, and marks steered items.

## Conventions

- Prefer **property tests over seeds** to single examples, and check the
  optimizer against **brute force** on pools small enough to enumerate.
- A bug fix comes with a test that fails without the fix.
- Tests may import private helpers (`_better_page`, `_swap_greedy`) when that is
  the only way to pin down behavior.
