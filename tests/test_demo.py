import pytest

from steerrec import demo
from steerrec.assembler import assemble
from steerrec.registry import DEFAULT_REGISTRY, single_slider
from steerrec.synthetic import make_catalog

P = 10


def test_demo_runs_and_prints_pages_and_sweep(capsys):
    assert demo.main(["--slider", "0.5", "--pool-size", "80", "--seed", "3"]) == 0
    out = capsys.readouterr().out
    assert "slider s = +0.50" in out
    assert "=== sweep" in out
    assert out.count("\n  +") + out.count("\n  -") >= 11


def test_demo_marks_steered_items():
    cat = make_catalog(120, seed=5)
    page = assemble(cat.items, single_slider(1.0), DEFAULT_REGISTRY, P)
    text = demo.render_page(1.0, page, cat, P)
    assert text.count(" * ") == len(page.steered_ids) > 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
