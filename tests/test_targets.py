import random

import pytest

from steerrec.items import Item
from steerrec.registry import DEFAULT_REGISTRY, EDUCATIONAL, LIGHT, Dimension, Registry, single_slider
from steerrec.targets import (
    BoundKind,
    compute_bounds,
    exclusive_mass,
    exclusive_share,
    total_share,
    unsteered_page,
)

P = 10


def random_pool(rng: random.Random, n: int, n_creators: int) -> list[Item]:
    return [
        Item(
            video_id=f"v{i:03d}",
            creator_id=f"c{rng.randrange(n_creators)}",
            p=rng.random(),
            q={EDUCATIONAL: rng.random(), LIGHT: rng.random()},
        )
        for i in range(n)
    ]


# --- U0 (Step 13) ---------------------------------------------------------------


def test_unsteered_page_is_top_p_by_relevance_one_per_creator():
    pool = [
        Item("a", "c1", 0.9),
        Item("b", "c1", 0.8),  # same creator as "a": skipped
        Item("c", "c2", 0.7),
        Item("d", "c3", 0.1),
    ]
    assert [it.video_id for it in unsteered_page(pool, 2)] == ["a", "c"]


def test_unsteered_page_ties_are_deterministic():
    pool = [Item("b", "c1", 0.5), Item("a", "c2", 0.5)]
    assert [it.video_id for it in unsteered_page(pool, 1)] == ["a"]


def test_identical_duplicates_are_kept_once():
    a = Item("a", "c1", 0.5, q={EDUCATIONAL: 0.1})
    assert unsteered_page([a, a, Item("b", "c2", 0.4)], 5) == [a, Item("b", "c2", 0.4)]


@pytest.mark.parametrize(
    "other",
    [
        Item("a", "c2", 0.5, q={EDUCATIONAL: 0.1}),  # different creator
        Item("a", "c1", 0.6, q={EDUCATIONAL: 0.1}),  # different p
        Item("a", "c1", 0.5, q={EDUCATIONAL: 0.9}),  # different q
    ],
)
def test_conflicting_duplicates_raise_in_either_order(other):
    a = Item("a", "c1", 0.5, q={EDUCATIONAL: 0.1})
    for pool in ([a, other], [other, a]):
        with pytest.raises(ValueError):
            unsteered_page(pool, 5)


def test_unsteered_page_handles_small_and_empty_pools():
    pool = [Item("a", "c1", 0.5), Item("b", "c1", 0.4)]
    assert [it.video_id for it in unsteered_page(pool, 10)] == ["a"]
    assert unsteered_page([], 10) == []


@pytest.mark.parametrize("seed", range(20))
def test_unsteered_page_matches_brute_force_definition(seed):
    rng = random.Random(seed)
    pool = random_pool(rng, 40, 12)
    best_per_creator = {}
    for it in pool:
        cur = best_per_creator.get(it.creator_id)
        if cur is None or (it.p, cur.video_id) > (cur.p, it.video_id):
            best_per_creator[it.creator_id] = it
    expected = sorted(best_per_creator.values(), key=lambda it: (-it.p, it.video_id))[:P]
    assert unsteered_page(pool, P) == expected


# --- exclusive mass (Step 14) -----------------------------------------------------


def test_exclusive_mass_formula():
    it = Item("v", "c", 0.5, q={EDUCATIONAL: 0.7, LIGHT: 0.9})
    assert exclusive_mass(it, LIGHT, pushed_up=(EDUCATIONAL,)) == pytest.approx(0.9 * 0.3)
    assert exclusive_mass(it, LIGHT, pushed_up=()) == pytest.approx(0.9)
    # A dimension is never "exclusive of" itself.
    assert exclusive_mass(it, EDUCATIONAL, pushed_up=(EDUCATIONAL,)) == pytest.approx(0.7)


# --- bounds (Step 14) -------------------------------------------------------------


def test_neutral_control_has_no_bounds():
    u0 = unsteered_page(random_pool(random.Random(0), 30, 10), P)
    assert compute_bounds(single_slider(0.0), u0, DEFAULT_REGISTRY, P) == []


def test_positive_slider_pushes_edu_up_and_light_down():
    u0 = unsteered_page(random_pool(random.Random(1), 30, 10), P)
    bounds = {b.dim_id: b for b in compute_bounds(single_slider(0.5), u0, DEFAULT_REGISTRY, P)}
    assert bounds[EDUCATIONAL].kind is BoundKind.LOWER_TOTAL
    assert bounds[LIGHT].kind is BoundKind.UPPER_EXCLUSIVE
    assert bounds[LIGHT].pushed_up == (EDUCATIONAL,)


@pytest.mark.parametrize("seed", range(30))
def test_targets_never_point_against_the_slider_and_tighten_with_abs_s(seed):
    rng = random.Random(seed)
    u0 = unsteered_page(random_pool(rng, 30, 10), P)
    for sign in (+1, -1):
        prev = {}
        for step in range(1, 11):
            s = sign * step / 10
            for b in compute_bounds(single_slider(s), u0, DEFAULT_REGISTRY, P):
                if b.kind is BoundKind.LOWER_TOTAL:
                    assert b.target >= b.reference - 1e-12
                    assert b.target >= prev.get(b.dim_id, -1.0) - 1e-12
                else:
                    assert b.target <= b.reference + 1e-12
                    assert b.target <= prev.get(b.dim_id, 2.0) + 1e-12
                prev[b.dim_id] = b.target


def test_full_slider_reaches_the_registry_end_points():
    u0 = [Item(f"v{i}", f"c{i}", 0.5, q={EDUCATIONAL: 0.2, LIGHT: 0.5}) for i in range(P)]
    bounds = {b.dim_id: b for b in compute_bounds(single_slider(1.0), u0, DEFAULT_REGISTRY, P)}
    assert bounds[EDUCATIONAL].reference == pytest.approx(0.2)
    assert bounds[EDUCATIONAL].target == pytest.approx(DEFAULT_REGISTRY[EDUCATIONAL].t_max)
    assert bounds[LIGHT].reference == pytest.approx(0.5 * 0.8)
    assert bounds[LIGHT].target == pytest.approx(DEFAULT_REGISTRY[LIGHT].t_min)


def test_reference_beyond_end_point_keeps_target_at_reference():
    # U0 is already more educational than T_max: pushing up must not lower the target.
    u0 = [Item(f"v{i}", f"c{i}", 0.5, q={EDUCATIONAL: 0.9, LIGHT: 0.01}) for i in range(P)]
    for s in (0.1, 0.5, 1.0):
        bounds = {b.dim_id: b for b in compute_bounds(single_slider(s), u0, DEFAULT_REGISTRY, P)}
        assert bounds[EDUCATIONAL].target == pytest.approx(0.9)
        # Exclusive light share (0.01 * 0.1 = 0.001) is already below T_min.
        assert bounds[LIGHT].target == pytest.approx(0.001)


def test_shares_are_normalized_by_page_size_not_pool_size():
    u0 = [Item("v", "c", 0.5, q={EDUCATIONAL: 1.0})]
    assert total_share(u0, EDUCATIONAL, P) == pytest.approx(0.1)
    assert exclusive_share(u0, EDUCATIONAL, (), P) == pytest.approx(0.1)


@pytest.mark.parametrize("s", [0.5, -0.5, 0.25, -0.8])
def test_targets_interpolate_linearly_in_abs_s(s):
    u0 = [Item(f"v{i}", f"c{i}", 0.5, q={EDUCATIONAL: 0.2, LIGHT: 0.5}) for i in range(P)]
    bounds = {b.dim_id: b for b in compute_bounds(single_slider(s), u0, DEFAULT_REGISTRY, P)}
    up, down = (EDUCATIONAL, LIGHT) if s > 0 else (LIGHT, EDUCATIONAL)
    u = 0.2 if up == EDUCATIONAL else 0.5
    q_down, q_up = (0.5, 0.2) if down == LIGHT else (0.2, 0.5)
    ubar = q_down * (1 - q_up)
    t_hi = max(DEFAULT_REGISTRY[up].t_max, u)
    t_lo = min(DEFAULT_REGISTRY[down].t_min, ubar)
    assert bounds[up].target == pytest.approx(u + abs(s) * (t_hi - u))
    assert bounds[down].target == pytest.approx(ubar - abs(s) * (ubar - t_lo))


def test_dimension_at_zero_is_unconstrained_and_not_pushed_up():
    reg = Registry([Dimension(EDUCATIONAL), Dimension(LIGHT), Dimension("calm")])
    u0 = [Item(f"v{i}", f"c{i}", 0.5, q={EDUCATIONAL: 0.3, LIGHT: 0.4, "calm": 0.5}) for i in range(P)]
    bounds = {b.dim_id: b for b in compute_bounds({EDUCATIONAL: 1, "calm": 0, LIGHT: -1}, u0, reg, P)}
    assert set(bounds) == {EDUCATIONAL, LIGHT}
    assert bounds[LIGHT].pushed_up == (EDUCATIONAL,)
    assert bounds[LIGHT].reference == pytest.approx(0.4 * 0.7)


def test_bounds_reject_bad_inputs():
    with pytest.raises(ValueError):
        compute_bounds(single_slider(0.5), [Item("v", "c", 0.5, q={"educationl": 0.5})], DEFAULT_REGISTRY, P)
    with pytest.raises(ValueError):  # longer than the page
        compute_bounds(single_slider(0.5), [Item(f"v{i}", f"c{i}", 0.5) for i in range(P + 1)], DEFAULT_REGISTRY, P)
    with pytest.raises(ValueError):  # repeated item
        compute_bounds(single_slider(0.5), [Item("v", "c", 0.5)] * 2, DEFAULT_REGISTRY, P)
    with pytest.raises(ValueError):  # repeated creator
        compute_bounds(single_slider(0.5), [Item("v", "c", 0.5), Item("w", "c", 0.5)], DEFAULT_REGISTRY, P)
    with pytest.raises(ValueError):  # bool is not a page size
        compute_bounds(single_slider(0.5), [], DEFAULT_REGISTRY, True)


def test_bounds_follow_registry_order_not_control_order():
    u0 = [Item(f"v{i}", f"c{i}", 0.5, q={EDUCATIONAL: 0.3, LIGHT: 0.4}) for i in range(P)]
    a = compute_bounds({LIGHT: -0.5, EDUCATIONAL: 0.5}, u0, DEFAULT_REGISTRY, P)
    b = compute_bounds({EDUCATIONAL: 0.5, LIGHT: -0.5}, u0, DEFAULT_REGISTRY, P)
    assert a == b
    assert [x.dim_id for x in a] == [EDUCATIONAL, LIGHT]


def test_n_dimensions_use_the_same_formulas():
    reg = Registry([Dimension(EDUCATIONAL), Dimension(LIGHT), Dimension("calm")])
    u0 = [Item(f"v{i}", f"c{i}", 0.5, q={EDUCATIONAL: 0.3, LIGHT: 0.4, "calm": 0.5}) for i in range(P)]
    bounds = {b.dim_id: b for b in compute_bounds({EDUCATIONAL: 1, "calm": 1, LIGHT: -1}, u0, reg, P)}
    assert set(bounds) == {EDUCATIONAL, LIGHT, "calm"}
    assert bounds[LIGHT].pushed_up == (EDUCATIONAL, "calm")
    assert bounds[LIGHT].reference == pytest.approx(0.4 * 0.7 * 0.5)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
