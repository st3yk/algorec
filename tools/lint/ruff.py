"""Runs the locked ruff binary from the PyPI wheel. See docs/guardrails.md."""

import os
import pathlib
import sys

import ruff


def ruff_bin() -> pathlib.Path:
    return pathlib.Path(ruff.__file__).parents[2] / "bin" / "ruff"


def main() -> int:
    workspace = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    if workspace:
        os.chdir(workspace)
    args = sys.argv[1:] or ["--version"]
    os.execv(ruff_bin(), [str(ruff_bin()), *args])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
