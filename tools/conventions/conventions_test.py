"""Runs the convention checks over the repository's files. See docs/guardrails.md."""

import os
import sys

from tools.conventions.conventions import check_repo

TEXT_SUFFIXES = (".py", ".md", ".bazel", ".proto", ".toml", ".ini", ".txt", ".sh", ".yml", ".json")


def load(root: str, paths: list[str]) -> dict[str, str | None]:
    files: dict[str, str | None] = {}
    for raw in paths:
        full = os.path.join(root, raw)
        path = raw.removeprefix("./")
        if path.endswith(TEXT_SUFFIXES):
            with open(full, encoding="utf-8") as f:
                files[path] = f.read()
        else:
            files[path] = None
    return files


def main(paths: list[str]) -> int:
    violations = check_repo(load(os.path.join(os.environ["TEST_SRCDIR"], "_main"), paths))
    for v in violations:
        print(v.render(), file=sys.stderr)
    if violations:
        print(f"\n{len(violations)} convention violation(s).", file=sys.stderr)
        return 1
    print(f"conventions: {len(paths)} files checked, no violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
