"""Smoke test: the hermetic toolchain provides the solver the assembler needs."""

import os
import sys

import pytest
import scipy
from scipy.optimize import milp  # noqa: F401  (import is the check: milp needs scipy >= 1.9)


def test_python_is_hermetic_3_12():
    assert sys.version_info[:2] == (3, 12)
    # The interpreter must be the one Bazel downloaded (it resolves into Bazel's
    # repository cache), not a system Python such as /usr/bin/python3.12.
    real = os.path.realpath(sys.executable)
    assert "bazel" in real and not real.startswith(("/usr/", "/bin/", "/opt/")), real


def test_scipy_has_milp():
    major, minor = (int(x) for x in scipy.__version__.split(".")[:2])
    assert (major, minor) >= (1, 9)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
