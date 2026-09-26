"""Steered page assembly: a small integer program solved in stages (slack, then
relevance, then clarity), with a greedy fallback, page ordering and shortfall.

See docs/code/assembler.md.
"""

import logging
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
from scipy.optimize import Bounds as VarBounds
from scipy.optimize import LinearConstraint, milp

from steerrec.items import Item
from steerrec.registry import Registry
from steerrec.targets import Bound, BoundKind, compute_bounds, dedupe_pool, unsteered_page

SLACK_TOL = 1e-6
CLARITY_TIE_BREAK = 1e-4

log = logging.getLogger(__name__)


class ShortfallKind(Enum):
    BOUND = "bound"
    CARDINALITY = "cardinality"


@dataclass(frozen=True)
class Shortfall:
    kind: ShortfallKind
    amount: float
    dim_id: str | None = None


@dataclass
class Page:
    items: list[Item]
    unsteered: list[Item]
    bounds: list[Bound]
    shortfalls: list[Shortfall] = field(default_factory=list)
    used_fallback: bool = False
    hit_time_limit: bool = False

    @property
    def steered_ids(self) -> set[str]:
        u0 = {it.video_id for it in self.unsteered}
        return {it.video_id for it in self.items if it.video_id not in u0}


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
    if not (math.isfinite(time_limit_s) and time_limit_s >= 0):
        raise ValueError(f"time_limit_s must be finite and >= 0, got {time_limit_s!r}")
    deadline = time.perf_counter() + time_limit_s
    pool = sorted(dedupe_pool(pool), key=lambda it: (-it.p, it.video_id))
    for item in pool:
        registry.check_scores(item.q)
    u0 = unsteered_page(pool, page_size)
    bounds = compute_bounds(control, u0, registry, page_size)

    if not bounds:
        return Page(items=list(u0), unsteered=u0, bounds=[], shortfalls=_shortfalls(u0, bounds, page_size))

    chosen, hit_limit = _solve_ilp(pool, bounds, registry, page_size, delta, deadline, solver)
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


def _solve_ilp(pool, bounds, registry, page_size, delta, deadline, solver) -> tuple[list[Item] | None, bool]:
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

    row = np.zeros(nvar)
    row[:n] = 1
    row[i_card] = 1
    add(row, page_size, page_size)
    row = np.zeros(nvar)
    row[:n] = 1
    add(row, len(unsteered_page(pool, page_size)), np.inf)
    for j, b in enumerate(bounds):
        row = np.zeros(nvar)
        row[:n] = [b.coefficient(it) for it in pool]
        if b.kind is BoundKind.LOWER_TOTAL:
            row[n + j] = 1
            add(row, b.mass, np.inf)
        else:
            row[n + j] = -1
            add(row, -np.inf, b.mass)
    for b in bounds:
        row = np.zeros(nvar)
        row[:n] = [b.coefficient(it) for it in pool]
        if b.kind is BoundKind.LOWER_TOTAL:
            add(row, b.reference * page_size - SLACK_TOL, np.inf)
        else:
            add(row, -np.inf, b.reference * page_size + SLACK_TOL)
    by_creator: dict[str, list[int]] = {}
    for i, it in enumerate(pool):
        by_creator.setdefault(it.creator_id, []).append(i)
    for idxs in by_creator.values():
        if len(idxs) > 1:
            row = np.zeros(nvar)
            row[idxs] = 1
            add(row, -np.inf, 1)

    limited = False

    def run(objective, extra_rows=(), extra_lo=(), extra_hi=(), ub=None, exact=False):
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
                options={"time_limit": remaining, **({"mip_rel_gap": 0.0} if exact else {})},
            )
        except Exception:
            log.warning("milp stage failed; using the previous stage's page", exc_info=True)
            return None
        if res.status == 1:
            limited = True
        if getattr(res, "x", None) is None or res.status not in (0, 1):
            return None
        return np.asarray(res.x)

    def page_of(x):
        return [it for it, xi in zip(pool, _binary(x[:n])) if xi]

    c0 = np.zeros(nvar)
    for j, b in enumerate(bounds):
        c0[n + j] = registry[b.dim_id].priority
    c0[i_card] = 1.0 + sum(registry[b.dim_id].priority for b in bounds)
    x0 = run(c0, exact=True)
    if x0 is None:
        return None, limited
    slack_cap = np.concatenate([np.ones(n), x0[n:] + SLACK_TOL])

    p = np.array([it.p for it in pool])
    c1 = np.zeros(nvar)
    c1[:n] = -p
    x1 = run(c1, ub=slack_cap)
    if x1 is None:
        greedy = _swap_greedy(pool, unsteered_page(pool, page_size), bounds, registry, page_size)
        return _better_page(page_of(x0), greedy, bounds, registry, page_size), limited
    r1 = float(p @ _binary(x1[:n]))

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


def _better_page(a, b, bounds, registry, page_size) -> list[Item]:
    va = _weighted_violation(a, bounds, registry, page_size)
    vb = _weighted_violation(b, bounds, registry, page_size)
    if abs(va - vb) > SLACK_TOL:
        return a if va < vb else b
    return a if sum(it.p for it in a) >= sum(it.p for it in b) else b


def _weighted_violation(items, bounds, registry, page_size) -> float:
    w_card = 1.0 + sum(registry[b.dim_id].priority for b in bounds)
    return sum(registry[b.dim_id].priority * _gap(b, items) for b in bounds) + w_card * (page_size - len(items))


def _gap(b: Bound, items) -> float:
    total = sum(b.coefficient(it) for it in items)
    if b.kind is BoundKind.LOWER_TOTAL:
        return max(0.0, b.mass - total)
    return max(0.0, total - b.mass)


def _swap_greedy(pool, u0, bounds, registry, page_size) -> list[Item]:
    weights = [registry[b.dim_id].priority for b in bounds]
    coef = {it.video_id: [b.coefficient(it) for b in bounds] for it in pool}
    lower = [b.kind is BoundKind.LOWER_TOTAL for b in bounds]
    masses = [b.mass for b in bounds]
    refs = [b.reference * page_size for b in bounds]

    def not_worse_than_neutral(totals):
        return all((t >= r - SLACK_TOL) if lo else (t <= r + SLACK_TOL) for t, r, lo in zip(totals, refs, lower))

    def violation(totals):
        return sum(
            w * (max(0.0, m - t) if lo else max(0.0, t - m)) for w, t, m, lo in zip(weights, totals, masses, lower)
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
        best = None
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


def _order(chosen: Sequence[Item], u0: Sequence[Item]) -> list[Item]:
    by_rel = lambda it: (-it.p, it.video_id)
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
