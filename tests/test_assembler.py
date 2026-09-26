import itertools
import random
from types import SimpleNamespace

import pytest
from scipy.optimize import milp

from steerrec.assembler import SLACK_TOL, ShortfallKind, assemble
from steerrec.items import Item
from steerrec.registry import DEFAULT_REGISTRY, EDUCATIONAL, LIGHT, single_slider
from steerrec.targets import BoundKind, compute_bounds, unsteered_page

P = 10


def random_pool(rng, n, n_creators, edu_bias=0.0):
    items = []
    for i in range(n):
        edu = min(1.0, max(0.0, rng.random() + edu_bias))
        items.append(
            Item(
                video_id=f"v{i:03d}",
                creator_id=f"c{rng.randrange(n_creators)}",
                p=rng.random(),
                q={EDUCATIONAL: edu, LIGHT: rng.random() * (1 - 0.6 * edu)},
            )
        )
    return items


def failing_solver(*args, **kwargs):
    raise RuntimeError("solver unavailable")


def gap(bound, items):
    total = sum(bound.coefficient(it) for it in items)
    return max(0.0, bound.mass - total) if bound.kind is BoundKind.LOWER_TOTAL else max(0.0, total - bound.mass)


@pytest.mark.parametrize("seed", range(10))
def test_neutral_page_is_exactly_u0(seed):
    pool = random_pool(random.Random(seed), 40, 15)
    page = assemble(pool, single_slider(0.0), DEFAULT_REGISTRY, P)
    assert page.items == unsteered_page(pool, P)
    assert page.bounds == [] and page.shortfalls == [] and not page.steered_ids


def test_full_slider_pulls_educational_items_in():
    light = [Item(f"l{i}", f"cl{i}", 0.9 - i * 0.01, q={EDUCATIONAL: 0.05, LIGHT: 0.9}) for i in range(10)]
    edu = [Item(f"e{i}", f"ce{i}", 0.5 - i * 0.01, q={EDUCATIONAL: 0.9, LIGHT: 0.1}) for i in range(10)]
    page = assemble(light + edu, single_slider(1.0), DEFAULT_REGISTRY, P)
    assert page.shortfalls == []
    edu_share = sum(it.q_of(EDUCATIONAL) for it in page.items) / P
    assert edu_share >= DEFAULT_REGISTRY[EDUCATIONAL].t_max - 1e-6
    assert page.steered_ids


def test_steered_items_are_evenly_spaced():
    light = [Item(f"l{i}", f"cl{i}", 0.9 - i * 0.01, q={EDUCATIONAL: 0.0, LIGHT: 0.9}) for i in range(10)]
    edu = [Item(f"e{i}", f"ce{i}", 0.5 - i * 0.01, q={EDUCATIONAL: 1.0, LIGHT: 0.0}) for i in range(10)]
    page = assemble(light + edu, {EDUCATIONAL: 0.5}, DEFAULT_REGISTRY, P)
    positions = [k + 1 for k, it in enumerate(page.items) if it.video_id in page.steered_ids]
    assert positions == [2, 5, 8]


@pytest.mark.parametrize("n", range(1, 13))
def test_steered_positions_are_distinct_and_evenly_spread_for_every_count(n):
    from steerrec.assembler import _order

    for k in range(n + 1):
        u0 = [Item(f"u{i}", f"cu{i}", 0.9 - i * 0.01) for i in range(n - k)]
        steered = [Item(f"s{i}", f"cs{i}", 0.5 - i * 0.01) for i in range(k)]
        page = _order(u0 + steered, u0)
        assert len(page) == n and {it.video_id for it in page} == {it.video_id for it in u0 + steered}
        pos = [i for i, it in enumerate(page) if it.video_id.startswith("s")]
        if 0 < k < n:
            gaps = [b - a for a, b in zip(pos, pos[1:])]
            assert not gaps or max(gaps) - min(gaps) <= 1
            assert pos[0] <= n / k and (n - 1 - pos[-1]) <= n / k


def test_unknown_score_key_anywhere_in_pool_is_rejected():
    pool = [Item(f"v{i}", f"c{i}", 0.9 - i * 0.01, q={EDUCATIONAL: 0.1}) for i in range(P)]
    pool.append(Item("bad", "cx", 0.01, q={"educationl": 0.9}))
    with pytest.raises(ValueError):
        assemble(pool, single_slider(0.5), DEFAULT_REGISTRY, P)


@pytest.mark.parametrize(
    "pool",
    [
        [],
        [Item("a", "c1", 0.5, q={EDUCATIONAL: 0.1})],
        [Item(f"v{i}", "same", 0.5, q={EDUCATIONAL: 0.9}) for i in range(20)],
        [Item(f"v{i}", f"c{i}", 0.5, q={LIGHT: 1.0}) for i in range(20)],
    ],
    ids=["empty", "one-item", "one-creator", "all-light"],
)
@pytest.mark.parametrize("s", [-1.0, -0.3, 0.3, 1.0])
def test_degenerate_pools_never_raise_and_report_shortfall(pool, s):
    page = assemble(pool, single_slider(s), DEFAULT_REGISTRY, P)
    assert len({it.creator_id for it in page.items}) == len(page.items)
    reported = {(sf.kind, sf.dim_id): sf.amount for sf in page.shortfalls}
    for b in page.bounds:
        g = gap(b, page.items)
        if g > SLACK_TOL:
            assert reported[(ShortfallKind.BOUND, b.dim_id)] == pytest.approx(g)
    if len(page.items) < P:
        assert reported[(ShortfallKind.CARDINALITY, None)] == pytest.approx(P - len(page.items))


def test_all_light_pool_at_max_learning_fills_page_and_reports_both_shortfalls():
    pool = [Item(f"v{i}", f"c{i}", 0.5, q={LIGHT: 1.0}) for i in range(20)]
    page = assemble(pool, single_slider(1.0), DEFAULT_REGISTRY, P)
    assert len(page.items) == P
    reported = {sf.dim_id: sf.amount for sf in page.shortfalls if sf.kind is ShortfallKind.BOUND}
    assert reported == {EDUCATIONAL: pytest.approx(6.0), LIGHT: pytest.approx(9.0)}


@pytest.mark.parametrize("seed", range(20))
def test_bounds_are_met_whenever_supply_makes_them_feasible(seed):
    rng = random.Random(seed)
    edu = [Item(f"e{i}", f"ce{i}", rng.uniform(0.05, 0.6), q={EDUCATIONAL: 1.0, LIGHT: 0.0}) for i in range(15)]
    light = [Item(f"l{i}", f"cl{i}", rng.uniform(0.4, 1.0), q={EDUCATIONAL: 0.0, LIGHT: 1.0}) for i in range(15)]
    mixed = random_pool(rng, 30, 25)
    for s in (-1.0, -0.5, 0.5, 1.0):
        page = assemble(edu + light + mixed, single_slider(s), DEFAULT_REGISTRY, P)
        assert not page.used_fallback
        assert page.shortfalls == []
        for b in page.bounds:
            assert gap(b, page.items) <= SLACK_TOL


@pytest.mark.parametrize("seed", range(40))
def test_every_bound_is_met_or_its_gap_is_reported(seed):
    rng = random.Random(seed)
    pool = random_pool(rng, rng.randrange(5, 60), rng.randrange(3, 30), edu_bias=rng.uniform(-0.6, 0.2))
    s = rng.choice([-1.0, -0.6, -0.2, 0.2, 0.6, 1.0])
    page = assemble(pool, single_slider(s), DEFAULT_REGISTRY, P)
    assert not page.used_fallback and not page.hit_time_limit
    assert len({it.video_id for it in page.items}) == len(page.items)
    assert len({it.creator_id for it in page.items}) == len(page.items)
    reported = {sf.dim_id: sf.amount for sf in page.shortfalls if sf.kind is ShortfallKind.BOUND}
    for b in page.bounds:
        g = gap(b, page.items)
        if g > SLACK_TOL:
            assert reported[b.dim_id] == pytest.approx(g)
        else:
            assert b.dim_id not in reported


def clarity_pool(a, b):
    return [
        Item("L", "cL", 0.95, q={EDUCATIONAL: 0.0, LIGHT: 0.9}),
        Item("E1", "c1", 0.90, q={EDUCATIONAL: 1.0, LIGHT: 0.0}),
        Item("E2", "c2", 0.88, q={EDUCATIONAL: 1.0, LIGHT: 0.0}),
        a,
        b,
    ]


def free_slot(page):
    return ({it.video_id for it in page.items} - {"E1", "E2"}).pop()


def test_stage2_objective_is_q_times_q_minus_half():
    a = Item("A", "cA", 0.600, q={EDUCATIONAL: 0.3, LIGHT: 0.0})
    b = Item("B", "cB", 0.595, q={EDUCATIONAL: 0.0, LIGHT: 0.0})
    page = assemble(clarity_pool(a, b), single_slider(1.0), DEFAULT_REGISTRY, 3)
    assert free_slot(page) == "B"
    assert free_slot(assemble(clarity_pool(a, b), single_slider(1.0), DEFAULT_REGISTRY, 3, delta=0.0)) == "A"


def test_stage2_prefers_clear_items_within_delta_but_not_beyond():
    clear = Item("C", "cC", 0.59, q={EDUCATIONAL: 0.95, LIGHT: 0.0})
    vague = Item("D", "cD", 0.60, q={EDUCATIONAL: 0.55, LIGHT: 0.0})
    assert free_slot(assemble(clarity_pool(clear, vague), single_slider(1.0), DEFAULT_REGISTRY, 3)) == "C"
    far = Item("C", "cC", 0.20, q={EDUCATIONAL: 0.95, LIGHT: 0.0})
    assert free_slot(assemble(clarity_pool(far, vague), single_slider(1.0), DEFAULT_REGISTRY, 3)) == "D"


def test_stage2_breaks_clarity_ties_by_relevance_regardless_of_pool_order():
    light = [Item(f"l{i}", f"cl{i}", 0.90 - i * 0.01, q={EDUCATIONAL: 0.0, LIGHT: 0.9}) for i in range(10)]
    edu = [Item(f"e{i}", f"ce{i}", 0.5, q={EDUCATIONAL: 1.0, LIGHT: 0.0}) for i in range(10)]
    for pool in (light + edu, list(reversed(light + edu))):
        page = assemble(pool, single_slider(1.0), DEFAULT_REGISTRY, P)
        kept = [it.video_id for it in page.items if it.video_id.startswith("l")]
        assert kept == ["l0"]


@pytest.mark.slow
@pytest.mark.parametrize("seed", range(20))
def test_page_does_not_depend_on_pool_order_even_with_tied_scores(seed):
    rng = random.Random(seed)
    pool = [
        Item(
            f"v{i:03d}",
            f"c{rng.randrange(30)}",
            round(rng.random(), 1),
            q={EDUCATIONAL: round(rng.random(), 1), LIGHT: round(rng.random(), 1)},
        )
        for i in range(60)
    ]
    shuffled = pool[:]
    random.Random(seed + 1000).shuffle(shuffled)
    for s in (-1.0, -0.5, 0.5, 1.0):
        a = assemble(pool, single_slider(s), DEFAULT_REGISTRY, P)
        b = assemble(shuffled, single_slider(s), DEFAULT_REGISTRY, P)
        assert [it.video_id for it in a.items] == [it.video_id for it in b.items]


def test_creator_limited_pool_keeps_the_page_full():
    u = [Item(f"U{i}", f"c{i}", 0.9 - i * 0.001, q={EDUCATIONAL: 0.0, LIGHT: 0.0}) for i in range(1, 6)]
    u6 = Item("U6", "c6", 0.8, q={EDUCATIONAL: 0.0, LIGHT: 1.0})
    a = [Item(f"A{i}", f"c{i}", 0.3 - i * 0.001, q={EDUCATIONAL: 0.9, LIGHT: 1.0}) for i in range(1, 6)]
    page = assemble(u + [u6] + a, single_slider(1.0), DEFAULT_REGISTRY, 6)
    assert len(page.items) == 6
    assert all(sf.kind is not ShortfallKind.CARDINALITY for sf in page.shortfalls)


def test_shortfall_page_is_never_below_neutral_minimal_case():
    a = Item("A", "cA", 0.9, q={EDUCATIONAL: 0.5, LIGHT: 0.9})
    n = Item("N", "cN", 0.5, q={EDUCATIONAL: 0.3, LIGHT: 0.0})
    for solver in (milp, failing_solver):
        page = assemble([a, n], single_slider(1.0), DEFAULT_REGISTRY, 1, solver=solver)
        assert [it.video_id for it in page.items] == ["A"]
        assert {sf.dim_id for sf in page.shortfalls} == {EDUCATIONAL, LIGHT}


@pytest.mark.parametrize("seed", range(30))
def test_every_page_stays_on_the_slider_side_of_neutral(seed):
    rng = random.Random(seed)
    relevant = [
        Item(
            f"r{i}",
            f"cr{i}",
            rng.uniform(0.7, 0.95),
            q={EDUCATIONAL: rng.uniform(0.4, 0.55), LIGHT: rng.uniform(0.8, 1.0)},
        )
        for i in range(P)
    ]
    alternates = [
        Item(f"a{i}", f"ca{i}", rng.uniform(0.2, 0.6), q={EDUCATIONAL: rng.uniform(0.2, 0.35), LIGHT: 0.0})
        for i in range(P)
    ]
    pool = relevant + alternates
    for solver in (milp, failing_solver):
        page = assemble(pool, single_slider(1.0), DEFAULT_REGISTRY, P, solver=solver)
        assert page.shortfalls
        for b in page.bounds:
            realized = b.realized(page.items)
            if b.kind is BoundKind.LOWER_TOTAL:
                assert realized >= b.reference - 1e-6
            else:
                assert realized <= b.reference + 1e-6


def brute_force(pool, bounds, page_size, delta):
    pushed_up = bounds[0].pushed_up if bounds else ()
    w_card = 1.0 + len(bounds)
    best = []
    full = len(unsteered_page(pool, page_size))
    for k in range(full, page_size + 1):
        for combo in itertools.combinations(pool, k):
            if len({it.creator_id for it in combo}) < k:
                continue
            if not all(
                (b.realized(combo) >= b.reference - 1e-9)
                if b.kind is BoundKind.LOWER_TOTAL
                else (b.realized(combo) <= b.reference + 1e-9)
                for b in bounds
            ):
                continue
            slack = sum(gap(b, combo) for b in bounds) + w_card * (page_size - k)
            rel = sum(it.p for it in combo)
            clar = sum(it.q_of(d) * (it.q_of(d) - 0.5) for it in combo for d in pushed_up)
            best.append((slack, rel, clar))
    s0 = min(b[0] for b in best)
    r1 = max(b[1] for b in best if b[0] <= s0 + 1e-6)
    c2 = max(b[2] for b in best if b[0] <= s0 + 1e-6 and b[1] >= (1 - delta) * r1 - 1e-6)
    return s0, r1, c2


@pytest.mark.parametrize("seed", range(40))
def test_ilp_matches_brute_force_on_small_pools(seed):
    rng = random.Random(seed)
    page_size = 3
    pool = random_pool(rng, 8, 6, edu_bias=rng.uniform(-0.5, 0.3))
    s = rng.choice([-1.0, -0.5, 0.5, 1.0])
    page = assemble(pool, single_slider(s), DEFAULT_REGISTRY, page_size, delta=0.02)
    assert not page.used_fallback
    bounds = compute_bounds(single_slider(s), unsteered_page(pool, page_size), DEFAULT_REGISTRY, page_size)
    s0, r1, c2 = brute_force(pool, bounds, page_size, 0.02)
    items = page.items
    slack = sum(gap(b, items) for b in bounds) + (1.0 + len(bounds)) * (page_size - len(items))
    rel = sum(it.p for it in items)
    pushed_up = bounds[0].pushed_up
    clar = sum(it.q_of(d) * (it.q_of(d) - 0.5) for it in items for d in pushed_up)
    assert slack == pytest.approx(s0, abs=1e-5)
    assert rel >= (1 - 0.02) * r1 - 1e-5
    assert clar == pytest.approx(c2, abs=1e-5)


EPS = 0.03


@pytest.mark.slow
@pytest.mark.parametrize("sign", [+1, -1])
def test_mean_realized_share_is_monotone_across_slider_points(sign):
    up, down = (EDUCATIONAL, LIGHT) if sign > 0 else (LIGHT, EDUCATIONAL)
    pools = []
    for seed in range(25):
        rng = random.Random(seed)
        pools.append(random_pool(rng, 60, 40, edu_bias=rng.uniform(-0.4, 0.2)))
    mean_m, mean_x = [], []
    for step in range(11):
        ms, xs = [], []
        for pool in pools:
            page = assemble(pool, single_slider(sign * step / 10), DEFAULT_REGISTRY, P)
            assert not page.used_fallback and not page.hit_time_limit
            if page.shortfalls:
                continue
            ms.append(sum(it.q_of(up) for it in page.items) / P)
            xs.append(sum(it.q_of(down) * (1 - it.q_of(up)) for it in page.items) / P)
        assert len(ms) >= 15, "too many shortfall pages for the mean to mean anything"
        mean_m.append(sum(ms) / len(ms))
        mean_x.append(sum(xs) / len(xs))
    for a, b in zip(mean_m, mean_m[1:]):
        assert b >= a - EPS
    for a, b in zip(mean_x, mean_x[1:]):
        assert b <= a + EPS
    assert mean_m[-1] - mean_m[0] >= 0.15
    assert mean_x[0] - mean_x[-1] >= 0.05


def test_time_limited_stage_is_reported_not_silent():
    rng = random.Random(0)
    pool = random_pool(rng, 300, 150)
    page = assemble(pool, single_slider(0.5), DEFAULT_REGISTRY, P, time_limit_s=1e-4)
    assert page.hit_time_limit or page.used_fallback
    reported = {sf.dim_id: sf.amount for sf in page.shortfalls if sf.kind is ShortfallKind.BOUND}
    for b in page.bounds:
        g = gap(b, page.items)
        assert g <= SLACK_TOL or reported[b.dim_id] == pytest.approx(g)


def test_a_300_item_pool_is_solved_to_optimality_given_enough_time():
    from steerrec.synthetic import make_catalog

    cat = make_catalog(300, seed=0)
    page = assemble(cat.items, single_slider(0.5), DEFAULT_REGISTRY, P, time_limit_s=60.0)
    assert not page.hit_time_limit and not page.used_fallback
    assert sum(it.p for it in page.items) / P > 0.84


@pytest.mark.timing
def test_default_time_limit_solves_a_300_item_pool_to_optimality():
    from steerrec.synthetic import make_catalog

    cat = make_catalog(300, seed=0)
    page = assemble(cat.items, single_slider(0.5), DEFAULT_REGISTRY, P)
    assert not page.hit_time_limit and not page.used_fallback
    assert sum(it.p for it in page.items) / P > 0.84


class ScriptedSolver:
    def __init__(self, script):
        self.script = script
        self.calls = 0

    def __call__(self, *args, **kwargs):
        stage, self.calls = self.calls, self.calls + 1
        action = self.script.get(stage)
        if action == "raise":
            raise RuntimeError("boom")
        res = milp(*args, **kwargs)
        if action == "limit_with_incumbent":
            return SimpleNamespace(status=1, x=res.x, success=False)
        if action == "limit_no_incumbent":
            return SimpleNamespace(status=1, x=None, success=False)
        return res


def easy_pool():
    light = [Item(f"l{i}", f"cl{i}", 0.9 - i * 0.01, q={EDUCATIONAL: 0.0, LIGHT: 0.9}) for i in range(10)]
    edu = [Item(f"e{i}", f"ce{i}", 0.5 - i * 0.01, q={EDUCATIONAL: 1.0, LIGHT: 0.0}) for i in range(10)]
    return light + edu


@pytest.mark.parametrize("stage", [0, 1, 2])
def test_stage_hitting_limit_with_incumbent_uses_it_and_reports(stage):
    page = assemble(
        easy_pool(), single_slider(1.0), DEFAULT_REGISTRY, P, solver=ScriptedSolver({stage: "limit_with_incumbent"})
    )
    assert page.hit_time_limit and not page.used_fallback
    assert page.shortfalls == []


def test_stage0_limit_without_incumbent_falls_back_to_greedy():
    page = assemble(
        easy_pool(), single_slider(1.0), DEFAULT_REGISTRY, P, solver=ScriptedSolver({0: "limit_no_incumbent"})
    )
    assert page.hit_time_limit and page.used_fallback


@pytest.mark.parametrize("action", ["limit_no_incumbent", "raise"])
@pytest.mark.parametrize("s", [-1.0, 0.5, 1.0])
def test_stage1_failure_serves_a_relevant_page_not_the_relevance_blind_stage0_one(action, s):
    from steerrec.synthetic import make_catalog

    cat = make_catalog(300, seed=0)
    page = assemble(cat.items, single_slider(s), DEFAULT_REGISTRY, P, solver=ScriptedSolver({1: action}))
    greedy = assemble(cat.items, single_slider(s), DEFAULT_REGISTRY, P, solver=failing_solver)
    assert not page.used_fallback
    assert page.shortfalls == greedy.shortfalls == []
    assert sum(it.p for it in page.items) >= sum(it.p for it in greedy.items) - 1e-9


def test_stage1_failure_prefers_the_stage0_page_when_greedy_stalls(monkeypatch):
    import steerrec.assembler as asm

    monkeypatch.setattr(asm, "_swap_greedy", lambda pool, u0, *a, **k: list(u0))
    page = assemble(easy_pool(), single_slider(1.0), DEFAULT_REGISTRY, P, solver=ScriptedSolver({1: "raise"}))
    assert page.shortfalls == []
    assert page.steered_ids


def test_better_page_treats_violations_within_tolerance_as_equal():
    from steerrec.assembler import SLACK_TOL, _better_page

    edu_bound = compute_bounds({EDUCATIONAL: 1.0}, [Item("u", "cu", 0.9, q={EDUCATIONAL: 0.0})], DEFAULT_REGISTRY, 1)
    a = [Item("a", "ca", 0.2, q={EDUCATIONAL: 0.0})]
    b = [Item("b", "cb", 0.9, q={EDUCATIONAL: SLACK_TOL / 10})]
    assert _better_page(a, b, edu_bound, DEFAULT_REGISTRY, 1) == b
    c = [Item("c", "cc", 0.1, q={EDUCATIONAL: 0.5})]
    assert _better_page(b, c, edu_bound, DEFAULT_REGISTRY, 1) == c


def test_only_stage0_is_solved_to_a_zero_mip_gap():
    seen = []

    def spy(*args, **kwargs):
        seen.append(kwargs["options"].get("mip_rel_gap"))
        return milp(*args, **kwargs)

    assemble(easy_pool(), single_slider(1.0), DEFAULT_REGISTRY, P, solver=spy)
    assert seen == [0.0, None, None]


def test_budget_includes_model_building(monkeypatch):
    import time

    from steerrec.registry import Registry

    real = Registry.check_scores

    def slow(self, q):
        time.sleep(0.01)
        return real(self, q)

    monkeypatch.setattr(Registry, "check_scores", slow)
    limits = []

    def spy(*args, **kwargs):
        limits.append(kwargs["options"]["time_limit"])
        return milp(*args, **kwargs)

    pool = easy_pool()
    assemble(pool, single_slider(1.0), DEFAULT_REGISTRY, P, time_limit_s=1.0, solver=spy)
    assert limits[0] < 0.85


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
def test_time_limit_must_be_finite_and_non_negative(bad):
    with pytest.raises(ValueError):
        assemble(easy_pool(), single_slider(1.0), DEFAULT_REGISTRY, P, time_limit_s=bad)


def test_budget_is_shared_across_stages():
    calls = []

    def spy(*args, **kwargs):
        calls.append(kwargs["options"]["time_limit"])
        return milp(*args, **kwargs)

    assemble(easy_pool(), single_slider(1.0), DEFAULT_REGISTRY, P, time_limit_s=1.0, solver=spy)
    assert len(calls) == 3
    assert calls[0] <= 1.0 and calls[1] < calls[0] and calls[2] < calls[1]


@pytest.mark.parametrize("seed", range(15))
def test_fallback_respects_creator_rule_and_reports_what_it_cannot_meet(seed):
    rng = random.Random(seed)
    pool = random_pool(rng, 40, 20, edu_bias=rng.uniform(-0.5, 0.2))
    page = assemble(pool, single_slider(1.0), DEFAULT_REGISTRY, P, solver=failing_solver)
    assert page.used_fallback
    assert len({it.creator_id for it in page.items}) == len(page.items)
    reported = {sf.dim_id: sf.amount for sf in page.shortfalls if sf.kind is ShortfallKind.BOUND}
    for b in page.bounds:
        g = gap(b, page.items)
        assert g <= SLACK_TOL or reported[b.dim_id] == pytest.approx(g)


def naive_swap_greedy(pool, u0, bounds, page_size):
    def violation(items):
        return sum(gap(b, items) for b in bounds)

    page = list(u0)
    while violation(page) > SLACK_TOL:
        in_page = {it.video_id for it in page}
        current = violation(page)
        best = None
        for out_idx in range(len(page)):
            creators = {it.creator_id for k, it in enumerate(page) if k != out_idx}
            for cand in pool:
                if cand.video_id in in_page or cand.creator_id in creators:
                    continue
                trial = page[:out_idx] + [cand] + page[out_idx + 1 :]
                v = violation(trial)
                key = (v, -sum(it.p for it in trial), out_idx, cand.video_id)
                if v < current - SLACK_TOL and (best is None or key < best[0]):
                    best = (key, out_idx, cand)
        if best is None:
            break
        page[best[1]] = best[2]
    return page


@pytest.mark.parametrize("seed", range(12))
def test_incremental_fallback_matches_the_naive_reference(seed):
    from steerrec.assembler import _swap_greedy

    rng = random.Random(seed)
    pool = random_pool(rng, 60, 30, edu_bias=rng.uniform(-0.5, 0.2))
    s = rng.choice([-1.0, -0.4, 0.4, 1.0])
    u0 = unsteered_page(pool, P)
    bounds = compute_bounds(single_slider(s), u0, DEFAULT_REGISTRY, P)
    fast = _swap_greedy(pool, u0, bounds, DEFAULT_REGISTRY, P)
    ref = naive_swap_greedy(pool, u0, bounds, P)
    assert [it.video_id for it in fast] == [it.video_id for it in ref]
    assert sum(gap(b, fast) for b in bounds) == pytest.approx(sum(gap(b, ref) for b in bounds))


def test_fallback_meets_bounds_when_an_easy_swap_exists():
    light = [Item(f"l{i}", f"cl{i}", 0.9 - i * 0.01, q={EDUCATIONAL: 0.0, LIGHT: 0.9}) for i in range(10)]
    edu = [Item(f"e{i}", f"ce{i}", 0.5 - i * 0.01, q={EDUCATIONAL: 1.0, LIGHT: 0.0}) for i in range(10)]
    page = assemble(light + edu, single_slider(1.0), DEFAULT_REGISTRY, P, solver=failing_solver)
    assert page.used_fallback and page.shortfalls == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
