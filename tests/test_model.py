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
    with pytest.raises(ValueError):
        Dimension("d", priority=0.5)


def test_control_is_clamped_and_unknown_dims_rejected():
    assert DEFAULT_REGISTRY.validate_control({EDUCATIONAL: 3, LIGHT: -7}) == {EDUCATIONAL: 1.0, LIGHT: -1.0}
    with pytest.raises(ValueError):
        DEFAULT_REGISTRY.validate_control({"calm": 0.5})


def test_single_slider_mapping():
    assert single_slider(0.4) == {EDUCATIONAL: 0.4, LIGHT: -0.4}


def test_empty_registry_rejected():
    with pytest.raises(ValueError):
        Registry([])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
