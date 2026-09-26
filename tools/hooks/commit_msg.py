"""git commit-msg hook: checks the message being committed with the same rules as the gate's
`commits` check. See docs/guardrails.md."""

import subprocess
import sys

from tools.verify_lib.commits import check_commits
from tools.verify_lib.gitutil import Commit


def main(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        lines = [line for line in f.read().splitlines() if not line.startswith("#")]
    subject = next((line for line in lines if line.strip()), "")
    body = "\n".join(lines[1:])
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], capture_output=True, text=True).stdout.split()
    findings = check_commits([Commit("0" * 40, subject, body, tuple(staged))])
    for finding in findings:
        print(f"commit-msg: {finding.message}\n  subject: {subject}", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
