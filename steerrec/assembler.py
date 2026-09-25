"""Steered page assembly: a small integer program solved in stages (plan Step 17).

Given a candidate pool and the user's control, pick P items that
  stage 0: miss the steering bounds (and the page size) as little as possible,
  stage 1: then maximize relevance without missing them any more than that,
  stage 2: then prefer clear examples of the pushed-up kind, giving up at most
           a fraction `delta` (plan: 0.02) of stage-1 relevance.
Solving the stages one after another (lexicographically) means no weight has to
trade relevance against the mix: the mix always comes first, relevance second.

If the solver fails, a swap-greedy fallback builds the page instead. Either way,
any unmet bound is returned as a Shortfall, never silently dropped.
"""

import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Mapping, Optional, Sequence

import numpy as np
from scipy.optimize import Bounds as VarBounds
from scipy.optimize import LinearConstraint, milp

from steerrec.items import Item
from steerrec.registry import Registry
from steerrec.targets import Bound, BoundKind, compute_bounds, dedupe_pool, unsteered_page

SLACK_TOL = 1e-6
# Stage 2 breaks clarity ties by relevance; this weight keeps relevance strictly secondary.
CLARITY_TIE_BREAK = 1e-4

log = logging.getLogger(__name__)


class ShortfallKind(Enum):
    BOUND = "bound"              # a steering bound could not be met
    CARDINALITY = "cardinality"  # fewer than P distinct-creator items available


@dataclass(frozen=True)
class Shortfall:
    kind: ShortfallKind
    amount: float                # missing mass, in items (e.g. 0.8 = most of one item)
    dim_id: Optional[str] = None


@dataclass
class Page:
    items: list[Item]                       # in display order
    unsteered: list[Item]                   # U0, the neutral reference
    bounds: list[Bound]
    shortfalls: list[Shortfall] = field(default_factory=list)
    used_fallback: bool = False
    hit_time_limit: bool = False            # the solve ran out of time; the page may be suboptimal

    @property
    def steered_ids(self) -> set[str]:
        """Items that are on the page only because of steering (not in U0)."""
        u0 = {it.video_id for it in self.unsteered}
        return {it.video_id for it in self.items if it.video_id not in u0}


# A solver has the signature of scipy.optimize.milp; injectable so tests can force the fallback.
Solver = Callable[..., object]


def assemble(
    pool: Sequence[Item],
    control: Mapping[str, float],
    registry: Registry,
    page_size: int = 10,
    delta: float = 0.02,
    time_limit_s: float = 2.0,
    solver: Solver = milp,
) -> Page:
    """Build one steered page from `pool` (plan Steps 13-17).

    `time_limit_s` is one wall-clock budget for all solver stages together. Each
    stage gets whatever is left. If a stage runs out of time or fails, the page
    from the previous stage is used (still slack-minimal after stage 0); only a
    stage-0 failure falls back to the greedy page. The plan's 50 ms assumed stages
    take "a few ms"; measured on a 300-item pool they take ~20-150 ms, and a
    50 ms cap gave noticeably worse pages (see the build log). This slice has no
    latency budget, so the default favors optimal pages; `hit_time_limit` reports
    any early stop.
    """
    # Canonical order: HiGHS resolves exact ties by variable order, so without this the
    # page could change when the caller shuffles the same pool.
    pool = sorted(dedupe_pool(pool), key=lambda it: (-it.p, it.video_id))
    for item in pool:
        registry.check_scores(item.q)
    u0 = unsteered_page(pool, page_size)
    bounds = compute_bounds(control, u0, registry, page_size)

    if not bounds:  # s = 0 everywhere: the page is exactly U0.
        return Page(items=list(u0), unsteered=u0, bounds=[], shortfalls=_shortfalls(u0, bounds, page_size))

    chosen, hit_limit = _solve_ilp(pool, bounds, registry, page_size, delta, time_limit_s, solver)
    used_fallback = chosen is None
    if used_fallback:
        chosen = _swap_greedy(pool, u0, bounds, registry, page_size)

    ordered = _order(chosen, u0)
    return Page(
        items=ordered,
        unsteered=u0,
        bounds=bounds,
        shortfalls=_shortfalls(ordered, bounds, page_size),
        used_fallback=used_fallback,
        hit_time_limit=hit_limit,
    )


# --- ILP -------------------------------------------------------------------------


def _solve_ilp(pool, bounds, registry, page_size, delta, time_limit_s, solver) -> tuple[Optional[list[Item]], bool]:
    """Stages 0-2. Returns (chosen items, or None if stage 0 gives no usable answer;
    whether the solve ran out of time).

    Variables: x_i (binary, one per pool item), then one slack per bound, then
    the cardinality slack. Every stage shares the same constraints, and U0 always
    satisfies them, so every stage is feasible.
    """
    n, nb = len(pool), len(bounds)
    nvar = n + nb + 1
    i_card = n + nb
    integrality = np.zeros(nvar)
    integrality[:n] = 1
    var_bounds = VarBounds(np.zeros(nvar), np.concatenate([np.ones(n), np.full(nb + 1, np.inf)]))

    rows, lo, hi = [], [], []

    def add(row, low, high):
        rows.append(row)
        lo.append(low)
        hi.append(high)

    # Page size: sum x + card_slack = P.
    row = np.zeros(nvar)
    row[:n] = 1
    row[i_card] = 1
    add(row, page_size, page_size)
    # Steering bounds, each softened by its own slack.
    for j, b in enumerate(bounds):
        row = np.zeros(nvar)
        row[:n] = [b.coefficient(it) for it in pool]
        if b.kind is BoundKind.LOWER_TOTAL:  # sum q x + slack >= mass
            row[n + j] = 1
            add(row, b.mass, np.inf)
        else:  # sum e x - slack <= mass
            row[n + j] = -1
            add(row, -np.inf, b.mass)
    # Never worse than neutral (plan Step 14's promise), even when a bound can't be met:
    # a pushed-up dimension keeps at least U0's mass, a pushed-down one at most U0's.
    # U0 itself satisfies these (and is a max-cardinality creator-respecting page), so
    # the model stays feasible. Without them, stage 0 could trade pushed-up mass away
    # to shrink the pushed-down slack and serve a page *less* educational than neutral.
    for b in bounds:
        row = np.zeros(nvar)
        row[:n] = [b.coefficient(it) for it in pool]
        if b.kind is BoundKind.LOWER_TOTAL:
            add(row, b.reference * page_size - SLACK_TOL, np.inf)
        else:
            add(row, -np.inf, b.reference * page_size + SLACK_TOL)
    # Creator rule (hard): at most one item per creator.
    by_creator: dict[str, list[int]] = {}
    for i, it in enumerate(pool):
        by_creator.setdefault(it.creator_id, []).append(i)
    for idxs in by_creator.values():
        if len(idxs) > 1:
            row = np.zeros(nvar)
            row[idxs] = 1
            add(row, -np.inf, 1)

    deadline = time.perf_counter() + time_limit_s
    limited = False

    def run(objective, extra_rows=(), extra_lo=(), extra_hi=(), ub=None):
        """One solver stage. Returns x, or None if out of time or the solver failed."""
        nonlocal limited
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            limited = True
            return None
        A = np.vstack(rows + list(extra_rows))
        vb = var_bounds if ub is None else VarBounds(np.zeros(nvar), ub)
        try:
            res = solver(
                objective,
                integrality=integrality,
                bounds=vb,
                constraints=[LinearConstraint(A, lo + list(extra_lo), hi + list(extra_hi))],
                options={"time_limit": remaining},
            )
        except Exception:  # noqa: BLE001 - only the solver call is guarded; model-building bugs still raise
            log.warning("milp stage failed; using the previous stage's page", exc_info=True)
            return None
        # status 0 = optimal; 1 = limit reached, usable only if an incumbent exists.
        if res.status == 1:
            limited = True
        if getattr(res, "x", None) is None or res.status not in (0, 1):
            return None
        return np.asarray(res.x)

    def page_of(x):
        return [it for it, xi in zip(pool, _binary(x[:n])) if xi]

    # Stage 0: minimize weighted slack. Cardinality outweighs every bound combined
    # (one item moves each bound's mass by at most 1), so the page is always filled first.
    c0 = np.zeros(nvar)
    for j, b in enumerate(bounds):
        c0[n + j] = registry[b.dim_id].priority
    c0[i_card] = 1.0 + sum(registry[b.dim_id].priority for b in bounds)
    x0 = run(c0)
    if x0 is None:
        return None, limited
    slack_cap = np.concatenate([np.ones(n), x0[n:] + SLACK_TOL])

    # Stage 1: maximize relevance with no more slack than stage 0 needed.
    p = np.array([it.p for it in pool])
    c1 = np.zeros(nvar)
    c1[:n] = -p
    x1 = run(c1, ub=slack_cap)
    if x1 is None:
        # Stage 0 knows nothing about relevance, so its page can be far worse than the
        # greedy fallback. Serve whichever is better: less weighted violation, then
        # more relevance.
        greedy = _swap_greedy(pool, unsteered_page(pool, page_size), bounds, registry, page_size)
        stage0 = page_of(x0)

        def quality(items):
            return (round(_weighted_violation(items, bounds, registry, page_size), 9), -sum(it.p for it in items))

        return min((stage0, greedy), key=quality), limited
    r1 = float(p @ _binary(x1[:n]))

    # Stage 2: prefer clear examples of pushed-up dimensions, losing at most delta of R1.
    # Among equally clear pages, a tiny relevance term picks the more relevant one;
    # otherwise the choice would be arbitrary and depend on pool order.
    pushed_up = bounds[0].pushed_up
    if not pushed_up:
        return page_of(x1), limited
    clarity = np.array([sum(it.q_of(d) * (it.q_of(d) - 0.5) for d in pushed_up) for it in pool])
    c2 = np.zeros(nvar)
    c2[:n] = -clarity - CLARITY_TIE_BREAK * p
    rel_row = np.zeros(nvar)
    rel_row[:n] = p
    x2 = run(c2, [rel_row], [(1.0 - delta) * r1 - SLACK_TOL], [np.inf], ub=slack_cap)
    return page_of(x2 if x2 is not None else x1), limited


def _binary(x: np.ndarray) -> np.ndarray:
    return (x > 0.5).astype(float)


# --- Fallback (plan Step 17) -------------------------------------------------------


def _weighted_violation(items, bounds, registry, page_size) -> float:
    """Stage-0 objective of a page: priority-weighted bound gaps plus the page-size gap."""
    w_card = 1.0 + sum(registry[b.dim_id].priority for b in bounds)
    return sum(registry[b.dim_id].priority * _gap(b, items) for b in bounds) + w_card * (page_size - len(items))


def _gap(b: Bound, items) -> float:
    total = sum(b.coefficient(it) for it in items)
    if b.kind is BoundKind.LOWER_TOTAL:
        return max(0.0, b.mass - total)
    return max(0.0, total - b.mass)


def _swap_greedy(pool, u0, bounds, registry, page_size) -> list[Item]:
    """Start from U0; repeatedly make the single swap that most reduces the bound
    violation (ties: higher resulting relevance), keeping one item per creator and
    never moving a dimension past U0 in the wrong direction.
    Stops when the bounds hold or no swap helps. Whatever is left is reported as
    shortfall by the caller.

    Per-bound totals are updated incrementally, so each round costs
    O(page * pool * bounds) arithmetic rather than re-summing every trial page.
    """
    weights = [registry[b.dim_id].priority for b in bounds]
    coef = {it.video_id: [b.coefficient(it) for b in bounds] for it in pool}
    lower = [b.kind is BoundKind.LOWER_TOTAL for b in bounds]
    masses = [b.mass for b in bounds]
    refs = [b.reference * page_size for b in bounds]

    def not_worse_than_neutral(totals):
        return all(
            (t >= r - SLACK_TOL) if lo else (t <= r + SLACK_TOL) for t, r, lo in zip(totals, refs, lower)
        )

    def violation(totals):
        return sum(
            w * (max(0.0, m - t) if lo else max(0.0, t - m))
            for w, t, m, lo in zip(weights, totals, masses, lower)
        )

    page = list(u0)
    totals = [sum(coef[it.video_id][j] for it in page) for j in range(len(bounds))]
    current = violation(totals)
    while current > SLACK_TOL:
        in_page = {it.video_id for it in page}
        creator_count: dict[str, int] = {}
        for it in page:
            creator_count[it.creator_id] = creator_count.get(it.creator_id, 0) + 1
        rel = sum(it.p for it in page)
        best = None  # (key, out_index, candidate, new_totals, new_violation)
        for out_idx, out_item in enumerate(page):
            out_c = coef[out_item.video_id]
            for cand in pool:
                if cand.video_id in in_page:
                    continue
                if creator_count.get(cand.creator_id, 0) - (cand.creator_id == out_item.creator_id) > 0:
                    continue
                in_c = coef[cand.video_id]
                new_totals = [t - o + i for t, o, i in zip(totals, out_c, in_c)]
                if not not_worse_than_neutral(new_totals):
                    continue
                v = violation(new_totals)
                if v >= current - SLACK_TOL:
                    continue
                key = (v, -(rel - out_item.p + cand.p), out_idx, cand.video_id)
                if best is None or key < best[0]:
                    best = (key, out_idx, cand, new_totals, v)
        if best is None:
            break
        _, out_idx, cand, totals, current = best
        page[out_idx] = cand
    return page


# --- Output ------------------------------------------------------------------------


def _order(chosen: Sequence[Item], u0: Sequence[Item]) -> list[Item]:
    """Steered items (not in U0) at evenly spaced positions; the rest by relevance.

    With k steered items on an n-item page, steered item j (0-based) goes to the
    1-based position nearest the middle of the j-th of k equal segments,
    floor((j + 0.5) * n / k + 0.5): 3 of 10 -> positions 2, 5, 8 (the plan's example).
    Positions are distinct because segments are longer than 1 when k < n.
    """
    by_rel = lambda it: (-it.p, it.video_id)  # noqa: E731
    u0_ids = {it.video_id for it in u0}
    steered = sorted((it for it in chosen if it.video_id not in u0_ids), key=by_rel)
    rest = sorted((it for it in chosen if it.video_id in u0_ids), key=by_rel)
    n, k = len(chosen), len(steered)
    if k in (0, n):
        return steered + rest
    slots = {math.floor((j + 0.5) * n / k + 0.5) - 1: it for j, it in enumerate(steered)}
    rest_iter = iter(rest)
    return [slots[pos] if pos in slots else next(rest_iter) for pos in range(n)]


def _shortfalls(items, bounds, page_size) -> list[Shortfall]:
    out = []
    for b in bounds:
        gap = _gap(b, items)
        if gap > SLACK_TOL:
            out.append(Shortfall(ShortfallKind.BOUND, gap, b.dim_id))
    if len(items) < page_size:
        out.append(Shortfall(ShortfallKind.CARDINALITY, float(page_size - len(items))))
    return out
