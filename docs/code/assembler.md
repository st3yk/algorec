# `assembler.py`: choosing and ordering the page

`assemble()` turns a pool and a control into a `Page`. The core is a small
integer program solved in three stages, one after another. Because relevance
is only optimized after the mix, no weight ever trades the mix against
relevance.

## Public API

### `assemble(pool, control, registry, page_size=10, delta=0.02, time_limit_s=2.0, solver=milp) -> Page`

1. Validates `time_limit_s`: it must be finite and ≥ 0. NaN used to mean "no
   limit".
2. Starts **one wall-clock budget** that covers model building and every solver
   stage. Each stage gets whatever time is left.
3. Deduplicates the pool and sorts it by `(-p, video_id)`. HiGHS resolves exact
   ties by variable order, so without this sort the page could change when the
   caller shuffles the same pool.
4. Checks every item's score keys against the registry.
5. Computes U0 and the bounds. With no bounds (s = 0 everywhere), it returns U0
   unchanged.
6. Runs `_solve_ilp`. If that yields no page, it uses `_swap_greedy`.
7. Orders the page with `_order` and computes shortfalls from the final page.

`solver` has the signature of `scipy.optimize.milp`. Tests inject a scripted
solver to force time limits and failures.

### `Page`

| Field | Meaning |
|---|---|
| `items` | The page, in display order. |
| `unsteered` | U0, the neutral reference. |
| `bounds` | The bounds this page was built against. |
| `shortfalls` | Every unmet bound, and any missing slots. |
| `used_fallback` | The solver gave no usable page, so the greedy page was served. |
| `hit_time_limit` | A stage ran out of time, so the page may be suboptimal. |
| `steered_ids` | Property: ids on the page that are not in U0. |

### `Shortfall(kind, amount, dim_id=None)`

- `kind` is `BOUND` (a steering bound was missed) or `CARDINALITY` (fewer than
  `P` distinct-creator items are available).
- `amount` is the missing mass in items. For example, 0.8 is most of one item.
- It is computed from the **served page** (`_gap`), not read from solver slack.
  At the optimum the two are equal. Computing it from the page keeps it correct
  for fallback pages too.

## The integer program (`_solve_ilp`)

**Variables**, in order: `x_i` (one binary per pool item), one continuous slack
per bound, and one cardinality slack.

**Constraints shared by every stage:**

| Row | Why |
|---|---|
| `Σx + σ_card = P` | Page size. The slack absorbs a real shortage. |
| `Σx ≥ \|U0\|` | U0 is the largest page the creator rule allows, so `σ_card` only ever measures a real shortage. Without this row, the "not worse than neutral" rows below could make dropping an item the cheapest way to satisfy them, and stage 0 would serve a short page although a full one exists. |
| `Σ q_d x + σ_d ≥ t_d P` (pushed up) / `Σ e_d x − σ_d ≤ t_d P` (pushed down) | The steering bounds, each softened by its own slack. |
| `Σ q_d x ≥ u_d P` (pushed up) / `Σ e_d x ≤ ū_d P` (pushed down), with a 1e-6 tolerance | **Never worse than neutral.** Stage 0 minimizes a *weighted sum* of misses. Without these rows it could trade pushed-up mass away to shrink the pushed-down miss, and serve a page at full "Learn" that is *less* educational than neutral. |
| `Σ_{i∈c} x_i ≤ 1` for each creator with more than one item | The creator rule is hard. A creator slack would let a steered page repeat a creator while U0 never does. A creator-limited pool shows up as a cardinality shortfall instead. |

U0 satisfies every row, so **every stage is always feasible**.

**Stages:**

| Stage | Objective (minimized) | Extra constraints |
|---|---|---|
| 0 | `Σ priority_d · σ_d + (1 + Σ priority_d) · σ_card` | Solved with `mip_rel_gap = 0`. Later stages cap slack at stage 0's value, so it must be truly minimal; the HiGHS default gap (1e-4) would let it stop short. |
| 1 | `−Σ p_i x_i` (maximize relevance). Gives R₁. | Every slack ≤ its stage-0 value + 1e-6. |
| 2 | `−Σ clarity_i x_i − 1e-4 · Σ p_i x_i` | Same slack caps, plus `Σ p_i x_i ≥ (1 − δ) R₁ − 1e-6`. |

- **Cardinality weight.** One item moves each bound's mass by at most 1, so a
  cardinality weight of `1 + Σ priority` makes filling a slot always beat any
  bound. Equal weights would tie, and the choice would be arbitrary.
- **Clarity.** `clarity_i = Σ_{d∈D⁺} q_d,i (q_d,i − 0.5)`. It prefers items that
  are clearly *d* over borderline ones, and it does not reward overshoot. A plain
  "maximize q" would prefer a q = 0.3 item over a q = 0 one. Pushed-down
  dimensions are not in the objective, so edutainment is not penalized. Stage 2
  is skipped when nothing is pushed up.
- **Clarity tie-break.** `CLARITY_TIE_BREAK = 1e-4` times relevance breaks clarity
  ties by relevance. Without it, the choice among equally clear pages would be
  arbitrary and would depend on pool order. It is a weighted sum, not a strict
  fourth stage: a clarity difference smaller than 1e-4 × the relevance
  difference goes to relevance.
- **Binarizing.** Solver values are read as `x > 0.5`.

### Solver outcomes and fallbacks

Each stage calls `run()`, which:
- returns `None` if the budget is already spent (and marks the page
  `hit_time_limit`);
- catches exceptions from the **solver call only**, so bugs in building the
  model still raise;
- accepts status 0 (optimal), and status 1 (limit reached) only when an
  incumbent `x` exists; status 1 marks `hit_time_limit`.

| What fails | What is served |
|---|---|
| Stage 2 | The stage-1 page. |
| Stage 1 | The better of the stage-0 page and the greedy page (`_better_page`). Stage 0 knows nothing about relevance, so its page alone can be far worse: mean p ~0.40 vs ~0.78 for greedy on one test pool. |
| Stage 0 | The greedy page (`used_fallback = True`). |

`_better_page(a, b)`: lower weighted violation wins. Violations within 1e-6
(the same tolerance that shortfalls and slack caps use) count as equal, and then
higher total relevance wins. Ties go to `a`.

### Time budget

The default is 2 s. Measured on a 300-item pool, stages take about 20–150 ms
each. With 50 ms per stage, stage 1 stopped early and silently served a worse
page (mean p 0.75 instead of 0.85 at s = 0.5). This slice has no latency budget,
so the default favors optimal pages, and `hit_time_limit` reports any early
stop. The greedy fallback is not bounded by the budget: it takes about 20 ms at
300 items and about 60 ms at 1,000.

## The greedy fallback (`_swap_greedy`)

1. Start from U0.
2. Each round, try every (page item out, pool item in) swap that:
   - keeps the creator rule;
   - keeps every dimension on the right side of U0 (the same "never worse than
     neutral" rule as the ILP);
   - strictly reduces the priority-weighted violation.
3. Take the swap with the lowest violation. Ties go to higher resulting
   relevance, then to position, then to `video_id`.
4. Stop when the bounds hold or no swap helps. The caller reports what is left as
   shortfall.

It tries every page item, not only the lowest-`p` one. If only the lowest-`p`
item could be swapped out, the search stalls as soon as that item is itself a
steered one. Per-bound totals are updated incrementally, so each round costs
O(page × pool × bounds) arithmetic instead of re-summing every trial page.

## Ordering (`_order`)

Steered items (not in U0) are spread evenly. The rest fill the gaps by
descending `p`. With `k` steered items on an `n`-item page, steered item `j`
(0-based, by descending `p`) goes to 1-based position
`floor((j + 0.5) · n / k + 0.5)`. For example, 3 of 10 go to positions 2, 5
and 8. Positions are distinct because each segment is longer than 1 when k < n.
If k is 0 or n, the page is simply sorted by `p`.

## Helpers

- `_gap(bound, items)`: `max(0, mass − total)` for a lower bound, and
  `max(0, total − mass)` for an upper bound.
- `_weighted_violation(items, ...)`: the stage-0 objective of a finished page.
- `_shortfalls(items, bounds, page_size)`: one `BOUND` shortfall per gap above
  1e-6, plus a `CARDINALITY` shortfall if the page is short.
- `SLACK_TOL = 1e-6`: the single tolerance for "met", for slack caps and for
  the neutral rows.
