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

- **Milestone / round**: M1, implementing
- **Last green commit**: none yet
- **Waiting on**: nothing
- **Next action**: Bazel skeleton (MODULE.bazel, .bazelversion, requirements lock, a smoke test)
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

## Plan deviations

| Plan step | Deviation | Why | Design-level? |
|---|---|---|---|

## Decisions
