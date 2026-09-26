"""Entry point of tools/verify: runs the base branch's copy of the judge against this
branch, so a branch can't weaken the checks that judge it. See docs/guardrails.md."""

import os
import subprocess
import sys
import tempfile

from tools.verify_lib import gitutil
from tools.verify_lib.verify import default_base, main

JUDGE_FILES = (
    "tools/__init__.py",
    "tools/verify_lib",
    "tools/proto_compat/__init__.py",
    "tools/proto_compat/listing.py",
)


def base_arg(argv: list[str]) -> str | None:
    for i, arg in enumerate(argv):
        if arg == "--base" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--base="):
            return arg.split("=", 1)[1]
    return None


def extract_judge(repo: str, ref: str, dest: str) -> bool:
    if gitutil.show(repo, ref, "tools/verify_lib/verify.py") is None:
        return False
    present = [p for p in JUDGE_FILES if gitutil.git(repo, "ls-tree", "--name-only", ref, "--", p, check=False).strip()]
    archive = subprocess.run(["git", "-C", repo, "archive", ref, *present], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", dest], input=archive, check=True)
    return True


def run(argv: list[str]) -> int:
    repo = gitutil.git(os.getcwd(), "rev-parse", "--show-toplevel").strip()
    if "--fast" in argv:
        return main([*argv, "--repo", repo])
    base = base_arg(argv) or default_base(repo)
    try:
        mb = gitutil.merge_base(repo, gitutil.rev(repo, base), gitutil.rev(repo, "HEAD"))
    except RuntimeError:
        return main([*argv, "--repo", repo, "--judge", "branch (the base could not be resolved)"])
    with tempfile.TemporaryDirectory(prefix="verify-judge-") as tmp:
        if not extract_judge(repo, mb, tmp):
            return main([*argv, "--repo", repo, "--judge", "branch (the base has no tools/verify)"])
        env = {**os.environ, "PYTHONPATH": tmp}
        command = [sys.executable, "-m", "tools.verify_lib.verify", *argv, "--repo", repo]
        command += ["--judge", f"base {mb[:12]} (tools/verify_lib from the merge-base)"]
        if not base_arg(argv):
            command += ["--base", base]
        return subprocess.run(command, env=env, cwd=tmp).returncode


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
