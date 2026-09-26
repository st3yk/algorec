import pytest

from steerrec.assembler import assemble
from steerrec.registry import DEFAULT_REGISTRY, EDUCATIONAL, LIGHT, Dimension, Registry, single_slider
from steerrec.synthetic import Kind, make_catalog

P = 10
EPS = 0.03


def test_catalog_is_deterministic_per_seed_and_differs_across_seeds():
    a, b, c = make_catalog(50, seed=1), make_catalog(50, seed=1), make_catalog(50, seed=2)
    assert a == b
    assert a.items != c.items


def test_catalog_kinds_and_scores_are_sensible():
    cat = make_catalog(2000, seed=0)
    share = {k: sum(1 for v in cat.kinds.values() if v is k) / 2000 for k in Kind}
    assert share[Kind.LIGHT] == pytest.approx(0.45, abs=0.04)
    assert share[Kind.EDUCATIONAL] == pytest.approx(0.25, abs=0.04)

    def mean(kind, f):
        vals = [f(it) for it in cat.items if cat.kinds[it.video_id] is kind]
        return sum(vals) / len(vals)

    assert mean(Kind.EDUCATIONAL, lambda it: it.q_of(EDUCATIONAL)) > 0.7
    assert mean(Kind.LIGHT, lambda it: it.q_of(LIGHT)) > 0.7
    assert mean(Kind.LIGHT, lambda it: it.p) > mean(Kind.EDUCATIONAL, lambda it: it.p) + 0.1


REGISTRIES = {
    "default": DEFAULT_REGISTRY,
    "left_active": Registry([Dimension(EDUCATIONAL, t_min=0.01), Dimension(LIGHT, t_max=0.9)]),
}


@pytest.mark.parametrize("registry_name", sorted(REGISTRIES))
def test_criterion_1_mean_share_is_monotone_over_synthetic_users(registry_name):
    registry = REGISTRIES[registry_name]
    catalogs = [make_catalog(150, n_creators=80, seed=seed) for seed in range(12)]
    points = [k / 10 for k in range(-10, 11, 2)]
    mean = {}
    for s in points:
        rows = []
        for cat in catalogs:
            page = assemble(cat.items, single_slider(s), registry, P)
            assert not page.used_fallback and not page.hit_time_limit
            if page.shortfalls:
                continue
            q = lambda it, d: it.q_of(d)
            rows.append(
                {
                    "edu": sum(q(it, EDUCATIONAL) for it in page.items) / P,
                    "light": sum(q(it, LIGHT) for it in page.items) / P,
                    "pure_edu": sum(q(it, EDUCATIONAL) * (1 - q(it, LIGHT)) for it in page.items) / P,
                    "pure_light": sum(q(it, LIGHT) * (1 - q(it, EDUCATIONAL)) for it in page.items) / P,
                }
            )
        assert len(rows) >= 8, f"too many shortfall pages at s={s}"
        mean[s] = {k: sum(r[k] for r in rows) / len(rows) for k in rows[0]}
    right = [s for s in points if s >= 0]
    left = [s for s in reversed(points) if s <= 0]
    for a, b in zip(right, right[1:]):
        assert mean[b]["edu"] >= mean[a]["edu"] - EPS
        assert mean[b]["pure_light"] <= mean[a]["pure_light"] + EPS
    for a, b in zip(left, left[1:]):
        assert mean[b]["light"] >= mean[a]["light"] - EPS
        assert mean[b]["pure_edu"] <= mean[a]["pure_edu"] + EPS
    assert mean[1.0]["edu"] - mean[0.0]["edu"] >= 0.2
    if registry_name == "left_active":
        assert mean[-1.0]["light"] - mean[0.0]["light"] >= 0.1
        assert mean[0.0]["pure_edu"] - mean[-1.0]["pure_edu"] >= 0.02


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
