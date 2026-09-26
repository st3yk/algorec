"""Type-checks steerrec/ and tools/ with mypy. See docs/guardrails.md."""

import os
import sys

from mypy import api


def main(files: list[str]) -> int:
    os.chdir(os.path.join(os.environ["TEST_SRCDIR"], "_main"))
    args = ["--config-file", "mypy.ini", "--cache-dir", os.devnull, "--explicit-package-bases", *files]
    stdout, stderr, status = api.run(args)
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
