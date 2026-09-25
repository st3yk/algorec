import pytest

from steerrec.assembler import assemble
from steerrec.registry import DEFAULT_REGISTRY, EDUCATIONAL, LIGHT, single_slider
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
    # The ranker stand-in favors light content, so the unsteered feed skews light.
    assert mean(Kind.LIGHT, lambda it: it.p) > mean(Kind.EDUCATIONAL, lambda it: it.p) + 0.1


def test_criterion_1_mean_share_is_monotone_over_synthetic_users():
    """Plan criterion 1 on synthetic data: 11 slider points, mean over users (catalog seeds),
    non-shortfall pages only. m_edu must not fall and pure-light share must not rise by
    more than EPS from one point to the next, for the plan's default delta = 0.02."""
    catalogs = [make_catalog(150, n_creators=80, seed=seed) for seed in range(12)]
    m_edu, x_light = [], []
    for k in range(-10, 11):
        ms, xs = [], []
        for cat in catalogs:
            page = assemble(cat.items, single_slider(k / 10), DEFAULT_REGISTRY, P)
            if page.shortfalls:
                continue
            ms.append(sum(it.q_of(EDUCATIONAL) for it in page.items) / P)
            xs.append(sum(it.q_of(LIGHT) * (1 - it.q_of(EDUCATIONAL)) for it in page.items) / P)
        assert len(ms) >= 8
        m_edu.append(sum(ms) / len(ms))
        x_light.append(sum(xs) / len(xs))
    for a, b in zip(m_edu, m_edu[1:]):
        assert b >= a - EPS, m_edu
    for a, b in zip(x_light, x_light[1:]):
        assert b <= a + EPS, x_light
    assert m_edu[-1] - m_edu[10] >= 0.2  # full right moves edu well past neutral


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
