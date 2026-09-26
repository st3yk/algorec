"""Builds a pull request description from the verify report, git history and the design
folder's logs, so the facts in a PR come from tools. See docs/guardrails.md."""

import argparse
import json
import os
import re
import sys

from tools.verify_lib import gitutil
from tools.verify_lib.findings import Finding
from tools.verify_lib.report import CheckResult, Report, render_markdown

PROSE_SECTIONS = ("Summary", "Why", "Not done")
REVIEW_FIX = re.compile(r"review finding", re.I)


def section(markdown: str, heading: str) -> str:
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)", markdown, re.M | re.S)
    return m.group(1).strip() if m else ""


def load_report(path: str) -> Report:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    report = Report(
        mode=data["mode"],
        sha=data["sha"],
        base=data.get("base", ""),
        merge_base=data.get("merge_base", ""),
        judge=data.get("judge", ""),
        reproduce=data.get("reproduce", ""),
        tools=data.get("tools", {}),
    )
    report.checks = [CheckResult(**c) for c in data["checks"]]
    report.findings = [Finding(**f) for f in data["findings"]]
    return report


def read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def commit_table(commits: list[gitutil.Commit]) -> str:
    lines = ["| Commit | Subject | Files |", "|---|---|---|"]
    for c in commits:
        tag = " *(review fix)*" if REVIEW_FIX.search(c.body) else ""
        subject = c.subject.replace("|", "\\|")
        lines.append(f"| `{c.short}` | {subject}{tag} | {len(c.files)} |")
    return "\n".join(lines)


def build(repo: str, slug: str, report: Report | None, base: str) -> str:
    design = os.path.join(repo, "design", slug)
    summary = read(os.path.join(design, "summary.md"))
    build_log = read(os.path.join(design, "build-log.md"))
    review_log = read(os.path.join(design, "review-log.md"))
    head = gitutil.rev(repo, "HEAD")
    mb = gitutil.merge_base(repo, gitutil.rev(repo, base), head)
    commits = gitutil.commits(repo, mb, head)
    parts: list[str] = []
    if report is None:
        parts.append(f"**`tools/verify` verdict: not run** at `{head[:12]}`. Run `tools/verify --base {base}`.")
    elif report.sha != head:
        parts.append(
            f"**`tools/verify` verdict: stale.** The report is for `{report.sha[:12]}`, not HEAD `{head[:12]}`."
        )
    else:
        parts.append(render_markdown(report).split("\n", 1)[0])
        human = [f for f in report.findings if f.level == "needs_human"]
        if human:
            parts.append(
                "### Needs a human\n\n" + "\n".join(f"- [{f.check}] `{f.where}`: {f.message}" for f in human[:40])
            )
    for heading in PROSE_SECTIONS[:2]:
        parts.append(
            f"## {heading}\n\n{section(summary, heading) or '_Not written: add it to design/' + slug + '/summary.md._'}"
        )
    parts.append(f"Plan: [`design/{slug}/plan.md`](design/{slug}/plan.md)")
    parts.append(f"## Commits ({len(commits)}, oldest first)\n\n{commit_table(commits)}")
    if report is not None and report.sha == head:
        parts.append("## Verification\n\n" + render_markdown(report))
    reviews = [line for line in review_log.splitlines() if line.startswith(("## ", "**Reviewed**"))]
    parts.append(
        "## Review rounds\n\n" + ("\n".join(f"- {line.lstrip('# ')}" for line in reviews) or "_No review log._")
    )
    deviations = section(build_log, "Plan deviations")
    parts.append("## Deviations from the plan\n\n" + (deviations or "_None recorded._"))
    parts.append(f"## {PROSE_SECTIONS[2]}\n\n{section(summary, PROSE_SECTIONS[2]) or '_Nothing recorded._'}")
    parts.append(
        "## How to check it yourself\n\n```sh\n"
        f"git fetch origin && git checkout {head[:12]}\n"
        f"tools/verify --base {base}\n"
        "bazel run //steerrec:demo -- --sweep-only\n```"
    )
    return "\n\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/pr_body", description=__doc__)
    parser.add_argument("slug", help="the design folder under design/")
    parser.add_argument("--base", default="origin/master")
    parser.add_argument("--report", help="a verify JSON report (default: the gate report for HEAD)")
    args = parser.parse_args(argv)
    repo = gitutil.git(os.getcwd(), "rev-parse", "--show-toplevel").strip()
    head = gitutil.rev(repo, "HEAD")
    path = args.report or os.path.join(repo, ".verify", "reports", f"{head[:12]}.json")
    report = load_report(path) if os.path.exists(path) else None
    sys.stdout.write(build(repo, args.slug, report, args.base))
    return 0


if __name__ == "__main__":
    sys.exit(main())
