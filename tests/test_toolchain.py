"""Smoke test: the hermetic toolchain provides the solver the assembler needs."""

import os
import sys

import pytest
import scipy
from scipy.optimize import milp  # noqa: F401  (import is the check: milp needs scipy >= 1.9)


def test_python_is_hermetic_3_12():
    assert sys.version_info[:2] == (3, 12)
    # The interpreter must be rules_python's downloaded 3.12, not a system Python.
    # sys.executable is a venv shim; one of its symlink hops names the toolchain repo
    # (e.g. .../rules_python++python+python_3_12_<platform>/bin/python3).
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
