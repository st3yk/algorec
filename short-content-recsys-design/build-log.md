# Build Log: Minimal steering core (video-free slice)

- **Plan**: `short-content-recsys-design/plan.md`
- **Branch**: `feat/steering-core` (base `main` @ `1410809`)
- **Build / test**: `bazel build //...` · `bazel test //...`

This log is the session's memory. Read it first when resuming. Update "Current state" before every long-running command and at every milestone boundary.

## Scope of this slice

This is a minimal, readable slice meant for understanding the core idea, with no videos and no ML training.
- **Items are synthetic**: each has an id, a creator, a relevance `p`, and calibrated dimension probabilities `q_educational` and `q_light_entertainment`. These stand in for the outputs of plan Steps 5–7 and 12.
- **Implemented**: plan Steps 8 (registry, minimal), 13–15 (neutral page and one-sided targets) and 17 (the lexicographic slack ILP with shortfall), plus property tests and a demo.
- **Out of scope**: retrieval and sources (9–11), the ranker (12), filters and floors (16), supply widening (18), exploration (19), the RPC (21–22), and ingestion (23).

## Current state

- **Milestone / round**: M1 review round 1 fixed (0 blockers, 1 major); M2 implemented, not yet committed
- **Last green commit**: `11644c8`
- **Waiting on**: nothing
- **Next action**: commit M2 (assembler + tests), then run M1 review round 2 and M2 review round 1
- **Blockers**: none

## Milestones

- [ ] **M1 — Build skeleton + model + targets** (plan Steps 8, 13, 14)
  - Acceptance:
    1. `bazel test //...` passes from a clean checkout with a hermetic Python and locked deps.
    2. `U0` = top-P by `p` with at most one item per creator.
    3. For s ≠ 0, pushed-up target `t ≥ u` and pushed-down target `t ≤ ū` (exclusive share), both monotone in |s|, with `T_hi = max(T_max, u)` and `T_lo = min(T_min, ū)`.
    4. Exclusive mass `e_d,i = q_d,i · Π_{k∈D⁺}(1 − q_k,i)`.
    5. s = 0 gives no dimension constraints.
  - Review: not started
- [ ] **M2 — Assembler ILP + shortfall** (plan Steps 15, 17)
  - Acceptance:
    1. Stage 0 minimizes weighted slack. Stage 1 maximizes relevance with slack capped at σ*. Stage 2 maximizes clarity `Σ_{d∈D⁺} q(q−0.5)` subject to relevance ≥ (1−δ)·R₁.
    2. Always feasible: any pool, including one smaller than P, one with a single creator, or an empty one, returns a result without raising.
    3. The bound is met within 1e-6, or its slack is reported as a shortfall.
    4. For a fixed pool, the realized share is monotone in |s| (pushed-up `m` non-decreasing, pushed-down `x` non-increasing).
    5. At s = 0 the page equals `U0`.
    6. Steered items (those not in `U0`) sit at evenly spaced positions.
    7. The fallback respects the creator rule and reports any remaining violation as shortfall.
  - Review: not started
- [ ] **M3 — Synthetic catalog + demo + README** (plan criterion 1 shape)
  - Acceptance:
    1. `bazel run //steerrec:demo` prints pages and shares for a slider sweep on a seeded synthetic pool.
    2. A sweep test shows mean shares monotone within ε = 0.03 across 11 slider points.
    3. The README explains the idea and maps the code to plan steps.
  - Review: not started

## Research notes

- **Bazel 9.2.0** is installed and current. The plan says 8.x; see Plan deviations.
- **rules_python 2.3.4** (latest in BCR). Bzlmod works with `python.toolchain(python_version="3.12", is_default=True)` plus `pip.parse(hub_name="pypi", ...)`. Deps are referenced as `@pypi//numpy`.
- **Locking**: `compile_pip_requirements` (from `@rules_python//python:pip.bzl`) works; `bazel run //:requirements.update` fills the lock even when it starts empty.
- **Locked versions**: numpy 2.5.3, scipy 1.18.1, pytest 9.1.1.
- **System Python** is 3.10 with scipy 1.8, which has no `milp` (added in 1.9). This confirms the hermetic toolchain is needed, not just nice to have.
- **`scipy.optimize.milp(c, *, integrality, bounds, constraints, options)`** (verified with a spike):
  - It *minimizes* `c @ x`.
  - `integrality` is 1 for integer variables, 0 for continuous ones.
  - Options include `time_limit` and `mip_rel_gap`.
  - The result has `status` (0 = optimal, 1 = time/iteration limit), `success`, `x`, `fun` and `mip_gap`.

## Plan deviations

| Plan step | Deviation | Why | Design-level? |
|---|---|---|---|
| Build System | Bazel 9.2.0 instead of 8.x | 9.2.0 is what's installed and current; nothing in the plan depends on 8.x | No |
| 17 | Creator rule is a **hard** constraint (no creator slack variable) | Cardinality slack alone already makes the ILP always feasible. A creator slack would let a steered page repeat a creator while U0 never does (U0 applies the rule strictly), making neutral and steered pages inconsistent. A creator-limited pool shows up as a cardinality shortfall | No |
| 18 | Shortfall reports `{dim, amount, kind}` with no `reason` attribution | Reasons (`pool_exhausted`, `below_relevance`, …) come from retrieval and filter stages, which are out of scope for this slice | No |
| Build System | `.bazelrc` uses `common --disk_cache` rather than `build --disk_cache` | `common` also applies the cache to `run` and `test` | No |
| Build System | One PyPI hub (`@pypi`); no `@pypi_gpu` hub | This slice has no GPU jobs (no video processing); the GPU hub comes with the feature-extraction jobs | No |
| 15 (finding) | The plan's claim "for a fixed pool the realized share is monotone in \|s\|" does **not** hold when two bounds move at once (edu up and light down). On random pools the realized share moved up to ~0.04 against the slider while staying inside its bound. This happens even with stage-2 δ = 0; δ = 0.02 makes it more frequent (up to ~0.05) | The nested-feasible-set argument covers one bound. With two, the relevance-optimal page can switch. What holds: every page meets its bound or reports the shortfall, and the **mean** share per slider point is monotone within ε = 0.03 (the plan's criterion 1), which is what the test checks | **Yes, for the plan's text**: Step 15's per-pool claim should be weakened to "bound met, or slack reported". No code change needed; flag for the next design pass |

## Decisions

- **Stage-0 weights**: cardinality slack weight = 1 + Σ_d priority_d. One item changes each bound's mass by at most 1, so this weight is the smallest that makes filling the page always beat leaving a slot empty to improve the mix. Equal weights (as the plan lists them) would tie, making the choice arbitrary and nondeterministic.
- **Shortfall amounts** are computed from the realized page (gap to each bound's mass), not read from solver slack values. They are equal at the optimum, and this stays correct when the fallback page is used.
- **Fallback swap-greedy** considers every (page item, candidate) pair, not only the lowest-p page item. Fixing the removal to the lowest-p item can stall as soon as that item is itself a steered one.

## Build review log

### M1 — Build skeleton + model + targets · Round 1

**Reviewed**: `272ffe1..d969367` · **Verdict**: blocker=0, major=1, minor=7, nit=3 → ITERATE

| Severity | Finding | Action |
|---|---|---|
| major | Bazel 9.2 vs the plan's 8.x (plus `common` vs `build` disk cache and the single PyPI hub) was not recorded in any committed build log, although the commit message said it was | Fixed: rows added to "Plan deviations"; the build log is committed |
| minor | Linear interpolation of targets not pinned for 0 < \|s\| < 1 | Fixed in `36c21cb` (tests at s = ±0.5, 0.25, −0.8) |
| minor | A dimension at s = 0 in N-dim not tested (≥ vs > mutation survived) | Fixed in `36c21cb` |
| minor | NaN slider value clamped to +1 | Fixed in `1eb0024` (rejected) |
| minor | U0 depends on pool order with duplicate (p, video_id) | Fixed in `36c21cb` (creator_id tie-break, dedupe by video_id) |
| minor | Duplicate dimension ids silently overwrite | Fixed in `1eb0024` |
| minor | Item score keys never checked against the registry | Fixed in `1eb0024` / `36c21cb` (`check_scores`, called in `compute_bounds`) |
| minor | BUILDING.md lists the not-yet-existing demo target | Fixed in `11644c8` |
| nit | compute_bounds doesn't check len(u0) ≤ page_size | Fixed in `36c21cb` |
| nit | Toolchain test doesn't prove the interpreter is hermetic | Fixed in `51aa320` |
| nit | Item.q mutable inside a frozen dataclass; items unhashable | Fixed in `1eb0024` |

