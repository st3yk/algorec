"""Applies ruff's safe fixes and formatting to the whole repository. See docs/guardrails.md."""

import os
import subprocess

from tools.lint.ruff import ruff_bin


def main() -> int:
    os.chdir(os.environ.get("BUILD_WORKSPACE_DIRECTORY", "."))
    check = subprocess.run([str(ruff_bin()), "check", "--fix", "."]).returncode
    fmt = subprocess.run([str(ruff_bin()), "format", "."]).returncode
    return check or fmt


if __name__ == "__main__":
    raise SystemExit(main())
