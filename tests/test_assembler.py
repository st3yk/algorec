import itertools
import random

import pytest

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


def gap(bound, items):
    total = sum(bound.coefficient(it) for it in items)
    return max(0.0, bound.mass - total) if bound.kind is BoundKind.LOWER_TOTAL else max(0.0, total - bound.mass)


# --- s = 0 and ordering ---------------------------------------------------------


@pytest.mark.parametrize("seed", range(10))
def test_neutral_page_is_exactly_u0(seed):
    pool = random_pool(random.Random(seed), 40, 15)
    page = assemble(pool, single_slider(0.0), DEFAULT_REGISTRY, P)
    assert page.items == unsteered_page(pool, P)
    assert page.bounds == [] and page.shortfalls == [] and not page.steered_ids


def test_full_slider_pulls_educational_items_in():
    # U0 is all light; plenty of relevant-enough educational items exist.
    light = [Item(f"l{i}", f"cl{i}", 0.9 - i * 0.01, q={EDUCATIONAL: 0.05, LIGHT: 0.9}) for i in range(10)]
    edu = [Item(f"e{i}", f"ce{i}", 0.5 - i * 0.01, q={EDUCATIONAL: 0.9, LIGHT: 0.1}) for i in range(10)]
    page = assemble(light + edu, single_slider(1.0), DEFAULT_REGISTRY, P)
    assert page.shortfalls == []
    edu_share = sum(it.q_of(EDUCATIONAL) for it in page.items) / P
    assert edu_share >= DEFAULT_REGISTRY[EDUCATIONAL].t_max - 1e-6
    assert page.steered_ids  # something had to change


def test_steered_items_are_evenly_spaced():
    light = [Item(f"l{i}", f"cl{i}", 0.9 - i * 0.01, q={EDUCATIONAL: 0.0, LIGHT: 0.9}) for i in range(10)]
    edu = [Item(f"e{i}", f"ce{i}", 0.5 - i * 0.01, q={EDUCATIONAL: 1.0, LIGHT: 0.0}) for i in range(10)]
    # Push only educational (light at 0 = unconstrained): t_edu = 0 + 0.5 * (0.6 - 0) -> 3 items.
    page = assemble(light + edu, {EDUCATIONAL: 0.5}, DEFAULT_REGISTRY, P)
    positions = [k + 1 for k, it in enumerate(page.items) if it.video_id in page.steered_ids]
    assert positions == [2, 5, 7]


def test_unknown_score_key_anywhere_in_pool_is_rejected():
    pool = [Item(f"v{i}", f"c{i}", 0.9 - i * 0.01, q={EDUCATIONAL: 0.1}) for i in range(P)]
    pool.append(Item("bad", "cx", 0.01, q={"educationl": 0.9}))  # not in U0, still rejected
    with pytest.raises(ValueError):
        assemble(pool, single_slider(0.5), DEFAULT_REGISTRY, P)


# --- always feasible, shortfall reported ------------------------------------------


@pytest.mark.parametrize(
    "pool",
    [
        [],
        [Item("a", "c1", 0.5, q={EDUCATIONAL: 0.1})],
        [Item(f"v{i}", "same", 0.5, q={EDUCATIONAL: 0.9}) for i in range(20)],
        [Item(f"v{i}", f"c{i}", 0.5, q={LIGHT: 1.0}) for i in range(20)],  # no educational supply at all
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
    # U0 is pure light: u_edu = 0 -> t_edu = 0.6 (mass 6); ubar_light = 1 -> t_light = 0.1 (mass 1).
    pool = [Item(f"v{i}", f"c{i}", 0.5, q={LIGHT: 1.0}) for i in range(20)]
    page = assemble(pool, single_slider(1.0), DEFAULT_REGISTRY, P)
    assert len(page.items) == P  # a full page beats an empty slot
    reported = {sf.dim_id: sf.amount for sf in page.shortfalls if sf.kind is ShortfallKind.BOUND}
    assert reported == {EDUCATIONAL: pytest.approx(6.0), LIGHT: pytest.approx(9.0)}


@pytest.mark.parametrize("seed", range(40))
def test_every_bound_is_met_or_its_gap_is_reported(seed):
    rng = random.Random(seed)
    pool = random_pool(rng, rng.randrange(5, 60), rng.randrange(3, 30), edu_bias=rng.uniform(-0.6, 0.2))
    s = rng.choice([-1.0, -0.6, -0.2, 0.2, 0.6, 1.0])
    page = assemble(pool, single_slider(s), DEFAULT_REGISTRY, P)
    assert len({it.video_id for it in page.items}) == len(page.items)
    assert len({it.creator_id for it in page.items}) == len(page.items)
    reported = {sf.dim_id: sf.amount for sf in page.shortfalls if sf.kind is ShortfallKind.BOUND}
    for b in page.bounds:
        g = gap(b, page.items)
        if g > SLACK_TOL:
            assert reported[b.dim_id] == pytest.approx(g)
        else:
            assert b.dim_id not in reported


# --- optimality against brute force (stages 0-2) ------------------------------------


def brute_force(pool, bounds, page_size, delta):
    """Enumerate every creator-respecting page; return (min slack, best relevance, best clarity)."""
    pushed_up = bounds[0].pushed_up if bounds else ()
    w_card = 1.0 + len(bounds)
    best = []
    for k in range(page_size + 1):
        for combo in itertools.combinations(pool, k):
            if len({it.creator_id for it in combo}) < k:
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
    assert slack == pytest.approx(s0, abs=1e-5)       # stage 0: least possible miss
    assert rel >= (1 - 0.02) * r1 - 1e-5               # stage 2 kept relevance within delta
    assert clar == pytest.approx(c2, abs=1e-5)         # stage 2: clearest such page


# --- monotonicity (plan Step 15 / criterion 1) --------------------------------------
# Per page, the guarantee is only "bound met or shortfall reported" (tested above).
# Per pool, the realized share is NOT exactly monotone in |s| when two bounds move at
# once (edu up and light down): the relevance-optimal page can switch, and the share
# can move ~0.04 against the slider while staying inside its bound. The plan's
# criterion 1 is therefore about the MEAN share per slider point, within 0.03, over
# pages without shortfall. That is what this test checks. (Stage 2's delta makes the
# per-pool dips more frequent, but they occur even with delta = 0.)

EPS = 0.03


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
            if page.shortfalls:
                continue  # criterion 1 reports shortfall pages separately
            ms.append(sum(it.q_of(up) for it in page.items) / P)
            xs.append(sum(it.q_of(down) * (1 - it.q_of(up)) for it in page.items) / P)
        assert len(ms) >= 15, "too many shortfall pages for the mean to mean anything"
        mean_m.append(sum(ms) / len(ms))
        mean_x.append(sum(xs) / len(xs))
    for a, b in zip(mean_m, mean_m[1:]):
        assert b >= a - EPS
    for a, b in zip(mean_x, mean_x[1:]):
        assert b <= a + EPS
    # And the sweep actually steers: the full slider moves the mean well past neutral.
    assert mean_m[-1] - mean_m[0] >= 0.15
    assert mean_x[0] - mean_x[-1] >= 0.05


# --- solver time limit ---------------------------------------------------------------


def test_time_limited_stage_is_reported_not_silent():
    rng = random.Random(0)
    pool = random_pool(rng, 300, 150)
    page = assemble(pool, single_slider(0.5), DEFAULT_REGISTRY, P, time_limit_s=1e-4)
    assert page.hit_time_limit or page.used_fallback
    reported = {sf.dim_id: sf.amount for sf in page.shortfalls if sf.kind is ShortfallKind.BOUND}
    for b in page.bounds:
        g = gap(b, page.items)
        assert g <= SLACK_TOL or reported[b.dim_id] == pytest.approx(g)


def test_default_time_limit_solves_a_300_item_pool_to_optimality():
    # Regression: with the plan's 50 ms per stage, stage 1 stopped early on this pool and
    # returned a page with mean p 0.75 instead of 0.85.
    from steerrec.synthetic import make_catalog

    cat = make_catalog(300, seed=0)
    page = assemble(cat.items, single_slider(0.5), DEFAULT_REGISTRY, P)
    assert not page.hit_time_limit and not page.used_fallback
    assert sum(it.p for it in page.items) / P > 0.84


# --- fallback ----------------------------------------------------------------------


def failing_solver(*args, **kwargs):
    raise RuntimeError("solver unavailable")


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


def test_fallback_meets_bounds_when_an_easy_swap_exists():
    light = [Item(f"l{i}", f"cl{i}", 0.9 - i * 0.01, q={EDUCATIONAL: 0.0, LIGHT: 0.9}) for i in range(10)]
    edu = [Item(f"e{i}", f"ce{i}", 0.5 - i * 0.01, q={EDUCATIONAL: 1.0, LIGHT: 0.0}) for i in range(10)]
    page = assemble(light + edu, single_slider(1.0), DEFAULT_REGISTRY, P, solver=failing_solver)
    assert page.used_fallback and page.shortfalls == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
