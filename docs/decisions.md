# Decisions and findings

These are the choices in the built code that are not obvious from reading it,
and what building it taught us. Record new ones here when you make them.

## Decisions

| Decision | Why |
|---|---|
| **The bounds are one-sided and relative to this request's U0** | The slider never sets an absolute mix, so it can never move the feed against itself relative to neutral. There is no stored baseline (EMA, frozen snapshot), so nothing can drift. |
| **The pushed-down bound counts exclusive ("pure") mass** | "More learning" should suppress content that is only light, not edutainment. |
| **Lexicographic stages instead of a weighted objective** | A weight between mix and relevance trades off differently on every request, because relevance scales differ. With stages, the mix always comes first. A greedy with a soft penalty was tried in design and settled below its target. |
| **Hard "never worse than neutral" rows, in the ILP and in the greedy** | Stage 0 alone (a weighted slack sum) could trade pushed-up mass for less pushed-down slack. |
| **Hard `Σx ≥ \|U0\|` row** | The neutral rows cap absolute mass, so without this row stage 0 could make a page shorter to meet them. Cardinality slack now means only a real shortage. |
| **Cardinality slack weight = 1 + Σ priority** | Filling a slot always beats a bound. Equal weights would tie, and the choice would be arbitrary. |
| **The creator rule is hard (no creator slack)** | U0 applies the rule strictly, so a steered page must too. Otherwise neutral and steered pages would be inconsistent. The cardinality slack alone already keeps the model feasible. |
| **Stage 0 is solved to a zero MIP gap** | Later stages cap slack at stage 0's value, so it must be truly minimal. |
| **A 1e-4 · p tie-break in stage 2** | Equally clear pages are otherwise chosen arbitrarily, and the choice depends on pool order. |
| **The pool is sorted canonically before the ILP** | HiGHS breaks exact ties by variable order. |
| **One 2 s wall-clock budget shared by all stages** | Measured stages take ~20–150 ms on 300 items. With 50 ms per stage, pages got silently worse. `hit_time_limit` reports any early stop. |
| **After a stage-1 failure, serve the better of the stage-0 and greedy pages** | Stage 0 ignores relevance, so its page alone can be very irrelevant. |
| **The greedy considers every (out, in) pair** | Swapping out only the lowest-`p` item stalls once that item is itself steered. |
| **Shortfall amounts come from the served page, not the solver's slack** | They are equal at the optimum, and computing from the page stays correct for fallback pages. |
| **A missing score reads as q = 0** | In the full system every item is scored for every dimension before retrieval, so this default only affects fixtures. Misspelled keys are still rejected. |
| **Shortfalls have a `kind` but no `reason`** | Reasons (`pool_exhausted`, `below_relevance`, …) come from the retrieval and filter stages, which don't exist yet. |
| **Steered items go to `floor((j + 0.5)·n/k + 0.5)`** | Spreads them evenly. For example, 3 of 10 go to positions 2, 5, 8. |
| **Bazel 9 with Bzlmod, one CPU-only PyPI hub, hermetic Python 3.12** | Reproducible builds. The system Python's scipy 1.8 has no `milp`. A GPU hub comes with the feature-extraction jobs. |
| **Wall-clock tests run alone, in their own tier** | The 2 s default budget test depends on the machine. Under a loaded machine (a reviewer running tests in parallel) or a slower CI runner it can fail with correct code. The optimality property is checked with a 30 s budget in the normal tier, and only "the default is enough" stays wall-clock bound, tagged `timing` and `exclusive`. |
| **Tiers are selected with pytest markers, not by moving tests** | Moving tests between files would churn history and docs. One `py_test` per tier over the same file, each with `-m`, keeps every test in one place and in exactly one target. |
| **ruff and mypy come from the locked PyPI wheels, run as `py_test`s** | They are pinned and hashed like every other dependency, cached by Bazel, and part of `bazel test //...`. A hand-written wrapper finds the wheel's `bin/ruff`; it needs no extra Bazel module. |
| **ruff ignores E501, E731 and B905** | The formatter owns line length. Assigned lambdas are used in the core. `zip(strict=)` would add runtime checks to the assembler. Exceptions live in `ruff.toml` because the no-comments rule rules out `# noqa`. |
| **`Solver` is `Callable[..., Any]`** | The assembler reads `.status` and `.x` from the result, which `object` doesn't allow; scipy ships no stubs for `milp`'s result. |
| **The proto contract is checked against a golden listing, not with buf** | `proto_library` already emits the descriptor set, so a small Python comparison needs no new toolchain. `update_golden` refuses breaking changes, so the golden only grows. |

## Findings from building the steering core

- **Per-user monotonicity does not hold with two bounds.** When edu moves up and
  light moves down together, the most relevant feasible page can switch, and the
  share can move about 0.04 against the slider (about 0.05 with δ = 0.02) while
  staying inside its bound. What holds: every page meets its bound or reports
  the shortfall, and the **mean** over users is monotone within 0.03.
- **Stage 2 switches on as a step.** The clarity objective isn't scaled by |s|.
  On 50 random pools, the page already differed from U0 at s = 1e-6 in all 50,
  and the mean edu share jumped 0.418 → 0.501 between s = 0 and s = 0.1, about
  30% of the whole sweep's range. Candidate fixes: scale δ by |s|, or skip stage
  2 when the stage-1 page equals U0.
- **Latency.** The 300 ms p95 target at ~500 candidates will need pool pruning
  (e.g. the top N by `p` per role), warm starts, or a faster formulation.
- **The left side of the demo is flat** because the synthetic user's neutral page
  is already past both left-side end points. This is by design: pushing never
  lowers a target.

## Considered and rejected

- **Filtering by label thresholds**: binary and brittle, and it empties the pool
  for niche users.
- **Re-ranking with a score bonus `λ·q_d`**: it doesn't guarantee a mix, and the
  pool may not contain enough wanted items.
- **Stochastic (Plackett-Luce) assembly with logged propensities**: it gives up
  the exact mix guarantee. Unbiased learning uses dedicated exploration slots
  instead.
- **Enumerating the four content categories without a solver**: valid for two
  dimensions but doesn't extend to N.
- **End-to-end control-conditioned ranking**: needs data logged under varied
  control settings first. Revisit once exploration logs exist.
