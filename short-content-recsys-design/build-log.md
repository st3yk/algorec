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

- **Milestone / round**: M1 round 2 fixed; M2 round 1 fixed; M3 implemented. Next is one combined fresh review: M1 round 3, M2 round 2, M3 round 1
- **Last green commit**: `b949a8e` (+ README wording fix)
- **Waiting on**: nothing
- **Next action**: combined review of `92720d7..HEAD`, then publish the change artifact

## Milestones

- [x] **M1 — Build skeleton + model + targets** (plan Steps 8, 13, 14)
  - Acceptance:
    1. `bazel test //...` passes from a clean checkout with a hermetic Python and locked deps.
    2. `U0` = top-P by `p` with at most one item per creator.
    3. For s ≠ 0, pushed-up target `t ≥ u` and pushed-down target `t ≤ ū` (exclusive share), both monotone in |s|, with `T_hi = max(T_max, u)` and `T_lo = min(T_min, ū)`.
    4. Exclusive mass `e_d,i = q_d,i · Π_{k∈D⁺}(1 − q_k,i)`.
    5. s = 0 gives no dimension constraints.
  - Review: round 1 ITERATE (0/1/7/3) → fixed; round 2 ITERATE (0/1/4/3) → fixed (see Build review log)
- [ ] **M2 — Assembler ILP + shortfall** (plan Steps 15, 17)
  - Acceptance:
    1. Stage 0 minimizes weighted slack. Stage 1 maximizes relevance with slack capped at σ*. Stage 2 maximizes clarity `Σ_{d∈D⁺} q(q−0.5)` subject to relevance ≥ (1−δ)·R₁.
    2. Always feasible: any pool, including one smaller than P, one with a single creator, or an empty one, returns a result without raising.
    3. The bound is met within 1e-6, or its slack is reported as a shortfall.
    4. The **mean** realized share per slider point is monotone within ε = 0.03 (pushed-up `m` non-decreasing, pushed-down `x` non-increasing) over non-shortfall pages. Per-pool monotonicity does not hold with two bounds; see the Step 15 finding.
    5. At s = 0 the page equals `U0`.
    6. Steered items (those not in `U0`) sit at evenly spaced positions.
    7. The fallback respects the creator rule and reports any remaining violation as shortfall.
  - Review: round 1 ITERATE (0/4/5/2) → fixed (see Build review log)
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
| 17 | Solver time limit: one 2 s budget shared by all stages (plan: fall back after 50 ms) | Measured on a 300-item pool: stages take ~20–150 ms. At 50 ms, stage 1 stopped early and silently returned a worse page (mean p 0.748 vs 0.853 optimal at s = 0.5). This slice has no latency budget, and `Page.hit_time_limit` now flags early stops | **Yes, for the plan's latency budget**: meeting 300 ms p95 at ~500 candidates needs pool pruning (e.g. keep the top-N by p per role), warm starts, or a faster formulation. Flag for the next design pass |
| 15 (finding) | The plan's claim "for a fixed pool the realized share is monotone in \|s\|" does **not** hold when two bounds move at once (edu up and light down). On random pools the realized share moved up to ~0.04 against the slider while staying inside its bound. This happens even with stage-2 δ = 0; δ = 0.02 makes it more frequent (up to ~0.05) | The nested-feasible-set argument covers one bound. With two, the relevance-optimal page can switch. What holds: every page meets its bound or reports the shortfall, and the **mean** share per slider point is monotone within ε = 0.03 (the plan's criterion 1), which is what the test checks | **Yes, for the plan's text**: Step 15's per-pool claim should be weakened to "bound met, or slack reported". No code change needed; flag for the next design pass |

## Decisions

- **Stage-0 weights**: cardinality slack weight = 1 + Σ_d priority_d. One item changes each bound's mass by at most 1, so this weight is the smallest that makes filling the page always beat leaving a slot empty to improve the mix. Equal weights (as the plan lists them) would tie, making the choice arbitrary and nondeterministic.
- **Shortfall amounts** are computed from the realized page (gap to each bound's mass), not read from solver slack values. They are equal at the optimum, and this stays correct when the fallback page is used.
- **Missing score = 0**: `Item.q_of` treats a dimension the item has no score for as q = 0 ("not that kind"). This is recorded rather than enforced (M1 round 2, minor 3). In the full system, every item is scored for every registered dimension before it can be retrieved (plan Step 23), so this only affects hand-built fixtures. Misspelled keys are still rejected by `check_scores`.
- **Stage 2 is a step at s ≠ 0** (demo finding, confirmed by the M2 reviewer): the clarity objective isn't scaled by |s|, so at δ = 0.02 any s ≠ 0 can already swap items. On the seed-0 pool that's 4 swaps at s = −0.2, the same as at s = −1. On 50 random pools the page differed from U0 at s = 1e-6 in 50/50 cases, and mean edu share jumped 0.418 → 0.501 from s = 0 to 0.1, about 30% of the whole sweep's range. Kept as the plan specifies. Scaling δ by |s|, or skipping stage 2 when the stage-1 page equals U0, is a candidate for the next design pass.
- **Stage-2 tie-break**: a 1e-4·p term in the stage-2 objective breaks clarity ties by relevance (M2 round 1, major 2). This is a small addition to the plan's objective, not a change to what it optimizes.
- **Page ordering**: steered item j goes to 1-based position floor((j + 0.5)·n/k + 0.5), which reproduces the plan's "2, 5, 8 for 3 items".
- **Left side flat on the demo pool**: the neutral page is already 0.69 light, above `T_max` = 0.6, so `max(T_max, u)` leaves no target to push toward. This is by design (pushing never lowers a target), and the README explains it.
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

### M1 — Build skeleton + model + targets · Round 2

**Reviewed**: `272ffe1..92720d7` (fix commits `d969367..92720d7`) · **Verdict**: blocker=0, major=1, minor=4, nit=3 → ITERATE

| Severity | Finding | Action |
|---|---|---|
| major | Conflicting duplicates (same id, creator and p, different q) still order-dependent | Fixed in `9f55e35`: `dedupe_pool` raises on conflicting duplicates and keeps identical ones once; the assembler uses it |
| minor | NaN/inf priority and out-of-range tau accepted | Fixed in `73f481c` |
| minor | Missing score silently counts as 0; not documented | Recorded in "Decisions" (every item is scored before retrieval in the full system) |
| minor | Interpolation test vacuous for edu pushed down (ubar = T_min) | Fixed in `7de0d3d` (fixture with references strictly inside the end points, asserted) |
| minor | Build-log commit mixed M2 content and had stale state | Addressed: this update refreshes "Current state" and milestone status. M2 entries stay, since M2 is committed as `a7febc2` |
| nit | Bounds follow control-dict order | Fixed in `9f55e35` (registry order) |
| nit | Hermetic-interpreter check fragile under custom output roots | Fixed in `b6ace17` (symlink chain into the rules_python python_3_12 repo) |
| nit | compute_bounds accepts bool page size / repeated u0 entries | Fixed in `9f55e35` |

The round-2 fixes are re-reviewed as **M1 round 3** by the same fresh reviewer that does M2 round 2 and M3 round 1. It gives one verdict per milestone.

### M2 — Assembler ILP + shortfall · Round 1

**Reviewed**: `92720d7..a7febc2` · **Verdict**: blocker=0, major=4, minor=5, nit=2 → ITERATE

| Severity | Finding | Action |
|---|---|---|
| major | Time limit per stage, not overall; results depend on machine load; the status-1 paths are untested | Partly fixed first in `a43cb26` (2 s default, `hit_time_limit`; found independently via the demo), then fully in `31af2d2`: one shared deadline, stage-by-stage fallback, scripted-solver tests for status 1 with and without an incumbent |
| major | Stage 2 spends δ for no clarity gain; the choice depends on pool order | Fixed in `d22018c` (1e-4·p tie-break, order-independence test) |
| major | Stage-2 objective barely tested (a `q` mutant passed) | Fixed in `d22018c` (fixtures pin q(q−0.5), the δ floor and the tie-break) |
| major | Ordering gives 2, 5, 7 vs the plan's 2, 5, 8, unrecorded | Fixed in `b1229bb` (2, 5, 8; property test over all n, k ≤ 12) |
| minor | Page jumps as the slider leaves 0 (stage 2 at s = ε) | Recorded as a design finding under "Decisions" (plan behavior; candidate fixes listed) |
| minor | `except Exception` hides model-building bugs | Fixed in `31af2d2` (only the solver call is guarded, failures logged) and `563ea9e` (tests assert the ILP path) |
| minor | A stage-1 failure discards stage 0's page | Fixed in `31af2d2` |
| minor | Shortfall tests close to tautological | Fixed in `563ea9e` (feasible-supply pools must have zero shortfall) |
| minor | Fallback slower than the budget it rescues | Fixed in `bb6ba10` (incremental totals: 100 → 20 ms at n = 300, 332 → 63 ms at n = 1,000; equivalence test against the naive reference) |
| nit | M2 acceptance item 4 contradicted the Step 15 finding; stale "Next action" | Fixed in this build-log update |
| nit | "medium" test size warning | Fixed in `b949a8e` |

