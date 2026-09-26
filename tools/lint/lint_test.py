"""Fails when ruff finds a lint error or unformatted code. See docs/guardrails.md."""

import os
import subprocess
import sys

from tools.lint.ruff import ruff_bin


def main(mode: str, files: list[str]) -> int:
    root = os.path.join(os.environ["TEST_SRCDIR"], "_main")
    command = ["check", "--no-cache"] if mode == "check" else ["format", "--check", "--diff", "--no-cache"]
    result = subprocess.run([str(ruff_bin()), *command, *files], cwd=root)
    if result.returncode:
        print(f"\nruff {mode} failed. Fix it with: bazel run //tools/lint:fix", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2:]))
