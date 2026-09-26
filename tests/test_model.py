import pytest

from steerrec.items import Item
from steerrec.registry import DEFAULT_REGISTRY, EDUCATIONAL, LIGHT, Dimension, Registry, single_slider


def test_item_rejects_non_probabilities():
    with pytest.raises(ValueError):
        Item("v", "c", p=1.5)
    with pytest.raises(ValueError):
        Item("v", "c", p=0.5, q={EDUCATIONAL: -0.1})


def test_missing_dimension_score_counts_as_zero():
    assert Item("v", "c", p=0.5).q_of(EDUCATIONAL) == 0.0


def test_dimension_validates_endpoints_and_priority():
    with pytest.raises(ValueError):
        Dimension("d", t_max=0.1, t_min=0.2)
    for bad in (0.5, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            Dimension("d", priority=bad)
    for bad in (-0.1, 7.0):
        with pytest.raises(ValueError):
            Dimension("d", tau=bad)


def test_control_is_clamped_and_unknown_dims_rejected():
    assert DEFAULT_REGISTRY.validate_control({EDUCATIONAL: 3, LIGHT: -7}) == {EDUCATIONAL: 1.0, LIGHT: -1.0}
    with pytest.raises(ValueError):
        DEFAULT_REGISTRY.validate_control({"calm": 0.5})


def test_nan_control_is_rejected_not_clamped_to_one():
    with pytest.raises(ValueError):
        DEFAULT_REGISTRY.validate_control({EDUCATIONAL: float("nan")})
    assert DEFAULT_REGISTRY.validate_control({EDUCATIONAL: float("inf")}) == {EDUCATIONAL: 1.0}


@pytest.mark.parametrize("bad", ["0.5", True, None])
def test_non_numeric_control_is_rejected(bad):
    with pytest.raises(ValueError):
        DEFAULT_REGISTRY.validate_control({EDUCATIONAL: bad})


def test_numpy_scalars_are_accepted():
    import numpy as np

    assert DEFAULT_REGISTRY.validate_control({EDUCATIONAL: np.float32(0.5), LIGHT: np.int64(-1)}) == {
        EDUCATIONAL: 0.5,
        LIGHT: -1.0,
    }


def test_duplicate_dimension_ids_rejected():
    with pytest.raises(ValueError):
        Registry([Dimension("e", t_max=0.6), Dimension("e", t_max=0.9)])


def test_unknown_score_keys_rejected():
    with pytest.raises(ValueError):
        DEFAULT_REGISTRY.check_scores({"educationl": 0.5})
    DEFAULT_REGISTRY.check_scores({EDUCATIONAL: 0.5, LIGHT: 0.1})


def test_item_scores_are_read_only_and_items_hashable():
    scores = {EDUCATIONAL: 0.5}
    it = Item("v", "c", 0.5, q=scores)
    scores[EDUCATIONAL] = 0.9
    assert it.q_of(EDUCATIONAL) == 0.5
    with pytest.raises(TypeError):
        it.q[EDUCATIONAL] = 0.9
    hash(it)


def test_single_slider_mapping():
    assert single_slider(0.4) == {EDUCATIONAL: 0.4, LIGHT: -0.4}


def test_empty_registry_rejected():
    with pytest.raises(ValueError):
        Registry([])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
