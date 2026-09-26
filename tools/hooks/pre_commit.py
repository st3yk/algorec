"""git pre-commit hook: ruff and the convention rules on the staged Python files.
See docs/guardrails.md."""

import subprocess
import sys

from tools.hooks.quick import check_files


def main() -> int:
    repo = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"], capture_output=True, text=True
    ).stdout.split()
    problems = check_files(repo, staged)
    if problems:
        print("pre-commit:\n" + "\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
