"""Smoke test: the hermetic toolchain provides the solver the assembler needs."""

import os
import sys

import pytest
import scipy
from scipy.optimize import milp


def test_python_is_hermetic_3_12():
    assert sys.version_info[:2] == (3, 12)
    hops, path = [], sys.executable
    for _ in range(10):
        hops.append(path)
        if not os.path.islink(path):
            break
        path = os.path.join(os.path.dirname(path), os.readlink(path))
    assert any("rules_python" in h and "python_3_12" in h for h in hops), hops


def test_scipy_has_milp():
    major, minor = (int(x) for x in scipy.__version__.split(".")[:2])
    assert (major, minor) >= (1, 9)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
