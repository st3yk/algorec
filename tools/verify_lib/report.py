"""The verify report: per-check results, the verdict, and its JSON and Markdown forms.
See docs/guardrails.md."""

import json
from dataclasses import asdict, dataclass, field

from tools.verify_lib.findings import FAIL, HUMAN, Finding

PASS_STATUS = "pass"
FAIL_STATUS = "fail"
HUMAN_STATUS = "needs_human"
ERROR_STATUS = "error"
SKIP_STATUS = "skip"

VERDICTS = {"PASS": 0, "FAIL": 1, "NEEDS_HUMAN": 2, "ERROR": 3}
HARD_CHECKS = ("base-guardrails",)


@dataclass
class CheckResult:
    name: str
    status: str
    seconds: float = 0.0
    summary: str = ""
    log: str = ""


@dataclass
class Report:
    mode: str
    sha: str
    base: str = ""
    merge_base: str = ""
    judge: str = ""
    checks: list[CheckResult] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    reproduce: str = ""
    tools: dict[str, str] = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        return verdict_of(self.checks, self.findings)

    @property
    def human_kind(self) -> str:
        if self.verdict != "NEEDS_HUMAN":
            return ""
        hard_check = any(c.status == HUMAN_STATUS and c.name in HARD_CHECKS for c in self.checks)
        if hard_check or any(f.hard for f in self.findings if f.level == HUMAN):
            return "hard"
        return "soft"

    @property
    def exit_code(self) -> int:
        return VERDICTS[self.verdict]

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["verdict"] = self.verdict
        data["human_kind"] = self.human_kind
        data["findings"] = [f.to_dict() for f in self.findings]
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def verdict_of(checks: list[CheckResult], findings: list[Finding]) -> str:
    statuses = {c.status for c in checks}
    levels = {f.level for f in findings}
    if ERROR_STATUS in statuses or not checks:
        return "ERROR"
    if FAIL_STATUS in statuses or FAIL in levels:
        return "FAIL"
    if HUMAN_STATUS in statuses or HUMAN in levels:
        return "NEEDS_HUMAN"
    return "PASS"


def render_text(report: Report) -> str:
    lines = [f"tools/verify {report.mode} @ {report.sha[:12]}" + (f" (base {report.base})" if report.base else "")]
    if report.judge:
        lines.append(f"judge: {report.judge}")
    for c in report.checks:
        lines.append(f"  {c.status.upper():<12} {c.name:<18} {c.seconds:6.1f}s  {c.summary}")
    for f in report.findings:
        lines.append(f"  - {f.level.upper()}: {f.render()}")
    for c in report.checks:
        if c.status in (FAIL_STATUS, ERROR_STATUS) and c.log:
            lines.append(f"\n--- {c.name} ---\n{c.log.rstrip()}")
    kind = f" ({report.human_kind})" if report.human_kind else ""
    lines.append(f"\nverdict: {report.verdict}{kind}")
    if report.reproduce:
        lines.append(f"reproduce: {report.reproduce}")
    return "\n".join(lines)


def render_markdown(report: Report) -> str:
    icon = {"PASS": "✅", "FAIL": "❌", "NEEDS_HUMAN": "⚠️", "ERROR": "💥"}[report.verdict]
    lines = [
        f"**`tools/verify` verdict: {icon} {report.verdict}"
        + (f" ({report.human_kind})" if report.human_kind else "")
        + f"** at `{report.sha[:12]}`"
        + (f" against `{report.base}` (merge-base `{report.merge_base[:12]}`)" if report.base else ""),
        "",
    ]
    if report.judge:
        lines += [f"Judge: {report.judge}", ""]
    lines += ["| Check | Status | Time | Summary |", "|---|---|---|---|"]
    for c in report.checks:
        summary = c.summary.replace("|", "\\|")
        lines.append(f"| `{c.name}` | {c.status} | {c.seconds:.1f}s | {summary} |")
    if report.findings:
        lines += ["", "Findings:", ""]
        for f in report.findings:
            where = f" `{f.where}`" if f.where else ""
            lines.append(f"- **{f.level}** [{f.check}]{where}: {f.message}")
    failing = [c for c in report.checks if c.status in (FAIL_STATUS, ERROR_STATUS) and c.log]
    for c in failing:
        lines += [
            "",
            f"<details><summary>{c.name} log</summary>",
            "",
            "```",
            c.log.rstrip()[-4000:],
            "```",
            "</details>",
        ]
    if report.reproduce:
        lines += ["", f"Reproduce: `{report.reproduce}`"]
    return "\n".join(lines) + "\n"
