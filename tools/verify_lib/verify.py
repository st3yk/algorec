"""The single judge of a change: runs every check and returns PASS, FAIL, NEEDS_HUMAN or
ERROR as its exit code. See docs/guardrails.md."""

import argparse
import contextlib
import fcntl
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator

from tools.verify_lib import gitutil
from tools.verify_lib.commits import check_commits
from tools.verify_lib.coverage import INPUTS, check_coverage, query_expression, source_paths
from tools.verify_lib.docs_changed import check_docs, load_map
from tools.verify_lib.evidence import check_evidence, collect_results, required_tests
from tools.verify_lib.findings import FAIL, HUMAN, Finding
from tools.verify_lib.guardrails import check_guardrails, is_guardrail
from tools.verify_lib.report import (
    ERROR_STATUS,
    FAIL_STATUS,
    HUMAN_STATUS,
    PASS_STATUS,
    SKIP_STATUS,
    CheckResult,
    Report,
    render_markdown,
    render_text,
)

FAILED_TARGET = re.compile(r"^(//\S+)\s+.*\b(FAILED|TIMEOUT|NO STATUS|FLAKY|INCOMPLETE)\b", re.M)
BAZEL_FAILURE_CODES = (1, 3)
VERIFY_TEST_FLAGS = ("--test_output=errors", "--flaky_test_attempts=1")
BASE_RULES_REJECT_CODES = (1, 2, 3)
LOG_TAIL = 60
BAZEL_ENV: dict[str, str] = {}
BAZEL_ERROR_LINE = re.compile(r"^(ERROR|FAIL|FAILED)\b|^//\S+\s+.*\b(FAILED|TIMEOUT|NO STATUS|FLAKY)\b")


def bazel(cwd: str, *args: str, timeout: float = 3600) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["bazel", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env={**os.environ, **BAZEL_ENV},
        )
    except FileNotFoundError:
        return 127, "bazel is not on PATH; install bazelisk (see BUILDING.md)"
    except subprocess.TimeoutExpired as e:
        stderr = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else e.stderr or ""
        return 124, f"bazel {' '.join(args)} timed out after {timeout:.0f}s\n{stderr}"
    return result.returncode, result.stdout + result.stderr


def bazel_stdout(cwd: str, *args: str) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["bazel", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            env={**os.environ, **BAZEL_ENV},
        )
    except FileNotFoundError:
        return 127, "bazel is not on PATH"
    return result.returncode, result.stdout if result.returncode == 0 else result.stdout + result.stderr


def tail(text: str, n: int = LOG_TAIL) -> str:
    return "\n".join(text.rstrip().splitlines()[-n:])


def bazel_errors(text: str, n: int = 30) -> str:
    lines = [line for line in text.splitlines() if BAZEL_ERROR_LINE.match(line)]
    return "\n".join(lines[:n]) if lines else tail(text, n)


def test_log(cwd: str, label: str) -> str:
    package, _, name = label[2:].partition(":")
    path = os.path.join(cwd, "bazel-testlogs", package, name, "test.log")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return tail(f.read(), 40)
    except OSError:
        return "(no test.log)"


def timed(name: str, fn: Callable[[], CheckResult]) -> CheckResult:
    start = time.monotonic()
    try:
        result = fn()
    except Exception as e:
        result = CheckResult(name, ERROR_STATUS, summary=f"{type(e).__name__}: {e}")
    result.seconds = time.monotonic() - start
    return result


def bazel_check(name: str, cwd: str, *args: str) -> CheckResult:
    code, out = bazel(cwd, *args)
    if code == 0:
        return CheckResult(name, PASS_STATUS, summary=f"bazel {args[0]} ok")
    status = FAIL_STATUS if code in BAZEL_FAILURE_CODES else ERROR_STATUS
    failed = sorted(set(m.group(1) for m in FAILED_TARGET.finditer(out)))
    summary = f"bazel exit {code}" + (f"; failing: {', '.join(failed[:6])}" if failed else "")
    logs = [f"==> {label}\n{test_log(cwd, label)}" for label in failed[:6]]
    return CheckResult(name, status, summary=summary, log="\n\n".join([bazel_errors(out), *logs]))


def coverage_check(cwd: str, tracked: list[str]) -> tuple[CheckResult, list[Finding]]:
    start = time.monotonic()
    result, findings = _coverage(cwd, tracked)
    result.seconds = time.monotonic() - start
    return result, findings


def _coverage(cwd: str, tracked: list[str]) -> tuple[CheckResult, list[Finding]]:
    seen: dict[str, set[str]] = {}
    for key, targets in INPUTS.items():
        code, out = bazel_stdout(cwd, "cquery", "--output=files", query_expression(targets))
        if code != 0:
            return CheckResult("coverage", ERROR_STATUS, summary=f"bazel cquery {key} inputs failed", log=tail(out)), []
        seen[key] = source_paths(out)
    findings = check_coverage(tracked, seen)
    status = FAIL_STATUS if findings else PASS_STATUS
    return CheckResult("coverage", status, summary=f"{len(tracked)} tracked files, {len(findings)} uncovered"), findings


def findings_check(name: str, findings: list[Finding]) -> CheckResult:
    levels = {f.level for f in findings}
    status = FAIL_STATUS if FAIL in levels else HUMAN_STATUS if HUMAN in levels else PASS_STATUS
    return CheckResult(name, status, summary=f"{len(findings)} finding(s)" if findings else "ok")


def cache_dir(repo: str) -> str:
    root = os.environ.get("STEERREC_VERIFY_DIR") or os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "steerrec-verify"
    )
    return os.path.join(root, hashlib.sha256(os.path.realpath(repo).encode()).hexdigest()[:12])


@contextlib.contextmanager
def locked(path: str) -> Iterator[None]:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def checkout(repo: str, wt: str, sha: str) -> None:
    if not os.path.exists(os.path.join(wt, ".git")):
        gitutil.git(repo, "worktree", "prune")
        gitutil.git(repo, "worktree", "add", "--detach", "--force", wt, sha)
    gitutil.git(wt, "checkout", "--detach", "--force", sha)
    gitutil.git(wt, "clean", "-ffdxq")


def clear_testlogs(wt: str) -> None:
    link = os.path.join(wt, "bazel-testlogs")
    if os.path.islink(link) or os.path.isdir(link):
        target = os.path.realpath(link)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)


def overlay_base_guardrails(repo: str, wt: str, mb: str) -> list[str]:
    paths = [p for p in gitutil.ls_tree(repo, mb, ".") if is_guardrail(p)]
    for path in paths:
        content = subprocess.run(["git", "-C", repo, "show", f"{mb}:{path}"], capture_output=True, check=True).stdout
        full = os.path.join(wt, path)
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        with open(full, "wb") as f:
            f.write(content)
    return paths


def tool_versions(cwd: str) -> dict[str, str]:
    code, out = bazel(cwd, "--version", timeout=120)
    git_version = gitutil.git(cwd, "--version").strip()
    return {"bazel": out.strip() if code == 0 else "unknown", "python": platform.python_version(), "git": git_version}


def run_fast(repo: str) -> Report:
    sha = gitutil.rev(repo, "HEAD")
    report = Report(mode="--fast", sha=sha, judge="the working tree's own checks", reproduce="tools/verify --fast")
    report.checks.append(
        timed("test (fast)", lambda: bazel_check("test (fast)", repo, "test", "//...", "--config=fast"))
    )
    tracked = gitutil.git(repo, "ls-files", "--cached", "--others", "--exclude-standard").split()
    tracked = [p for p in tracked if os.path.exists(os.path.join(repo, p))]
    result, findings = coverage_check(repo, tracked)
    report.checks.append(result)
    report.findings += findings
    return report


def judge_identity(repo: str, mb: str) -> tuple[str, bool]:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    base_files = [
        p
        for p in gitutil.ls_tree(repo, mb, "tools/verify_lib")
        if p.endswith((".py", ".json")) and not p.endswith("_selftest.py")
    ]
    if not base_files:
        return "this branch's own tools/verify_lib (the base has none)", False
    if os.path.realpath(root) == os.path.realpath(repo):
        return "this checkout's own tools/verify_lib, not the merge-base's", False
    ours = {f"tools/verify_lib/{name}" for name in os.listdir(here) if name.endswith((".py", ".json"))}
    ours = {p for p in ours if not p.endswith("_selftest.py")}
    if ours != set(base_files):
        return "a tools/verify_lib whose files differ from the merge-base's", False
    for path in base_files:
        with open(os.path.join(root, path), "rb") as f:
            if f.read() != gitutil.show_bytes(repo, mb, path):
                return f"a tools/verify_lib that differs from the merge-base's ({path})", False
    return f"base {mb[:12]}: tools/verify_lib matches the merge-base byte for byte", True


def run_gate(repo: str, base: str, deep: bool) -> Report:
    sha = gitutil.rev(repo, "HEAD")
    mode = "--deep" if deep else "gate"
    report = Report(mode=mode, sha=sha, base=base)
    report.reproduce = f"git checkout {sha[:12]} && tools/verify{' --deep' if deep else ''} --base {base}"
    dirty = gitutil.dirty_tracked(repo)
    if dirty:
        report.checks.append(
            CheckResult(
                "clean-tree",
                ERROR_STATUS,
                summary=f"{len(dirty)} uncommitted change(s), e.g. {dirty[0]}. The gate judges a commit: commit or stash first",
            )
        )
        return report
    try:
        base_sha = gitutil.rev(repo, base)
    except RuntimeError as e:
        report.checks.append(CheckResult("base", ERROR_STATUS, summary=str(e)))
        return report
    try:
        mb = gitutil.merge_base(repo, base_sha, sha)
    except RuntimeError:
        report.checks.append(
            CheckResult("base", ERROR_STATUS, summary=f"HEAD shares no history with {base} (shallow clone?)")
        )
        return report
    report.merge_base = mb
    if mb == sha:
        summary = f"nothing to judge: HEAD is already in {base}. Pass the branch's real base with --base"
        report.checks.append(CheckResult("base", ERROR_STATUS, summary=summary))
        return report
    BAZEL_ENV["BAZELISK_SKIP_WRAPPER"] = "1"
    base_version = (gitutil.show(repo, mb, ".bazelversion") or "").strip()
    if base_version:
        BAZEL_ENV["USE_BAZEL_VERSION"] = base_version
    report.judge, trusted = judge_identity(repo, mb)
    if not trusted:
        report.findings.append(Finding("judge", HUMAN, f"judged by {report.judge}"))

    commits = gitutil.commits(repo, mb, sha)
    changed = gitutil.changed_files(repo, mb, sha)
    head_files = gitutil.ls_tree(repo, sha, ".")
    base_files = gitutil.ls_tree(repo, mb, ".")
    commit_findings = check_commits(commits)
    docs_findings = check_docs(commits, load_map())
    guard_findings = check_guardrails(
        changed,
        base_files,
        head_files,
        lambda p: gitutil.show(repo, mb, p),
        lambda p: gitutil.show(repo, sha, p),
    )
    for name, found in (("commits", commit_findings), ("docs", docs_findings), ("guardrails", guard_findings)):
        report.checks.append(findings_check(name, found))
        report.findings += found

    wt = os.path.join(cache_dir(repo), "wt")
    with locked(wt + ".lock"):
        checkout(repo, wt, sha)
        report.tools = tool_versions(wt)
        build = timed("build", lambda: bazel_check("build", wt, "build", "//..."))
        report.checks.append(build)
        if build.status != PASS_STATUS:
            report.checks.append(CheckResult("test", SKIP_STATUS, summary="build failed"))
        else:
            clear_testlogs(wt)
            report.checks.append(timed("test", lambda: bazel_check("test", wt, "test", "//...", "--config=verify")))
            found = check_evidence(
                required_tests(head_files, lambda p: gitutil.show(repo, sha, p), lambda p: gitutil.show(repo, mb, p)),
                collect_results(os.path.join(wt, "bazel-testlogs")),
            )
            report.checks.append(findings_check("evidence", found))
            report.findings += found
            result, found = coverage_check(wt, head_files)
            report.checks.append(result)
            report.findings += found
            report.checks.append(
                timed("demo", lambda: bazel_check("demo", wt, "run", "//steerrec:demo", "--", "--sweep-only"))
            )
            if any(is_guardrail(p) for p in changed):
                report.checks.append(timed("base-guardrails", lambda: base_guardrails_check(repo, wt, mb, sha)))
            if deep:
                report.checks.append(timed("flakes", lambda: flakes_check(wt, changed)))
        checkout(repo, wt, sha)
    return report


def base_guardrails_check(repo: str, wt: str, mb: str, sha: str) -> CheckResult:
    overlaid = overlay_base_guardrails(repo, wt, mb)
    if not overlaid:
        return CheckResult("base-guardrails", SKIP_STATUS, summary="the base has no guardrail files to judge with")
    code, out = bazel(wt, "test", "//...", *VERIFY_TEST_FLAGS)
    if code == 0:
        return CheckResult(
            "base-guardrails", PASS_STATUS, summary=f"passes with the base's {len(overlaid)} guardrail files"
        )
    if code in BASE_RULES_REJECT_CODES:
        summary = (
            f"fails under the base's {len(overlaid)} guardrail files (bazel exit {code}): passes only by its own rules"
        )
        return CheckResult("base-guardrails", HUMAN_STATUS, summary=summary, log=bazel_errors(out))
    return CheckResult("base-guardrails", ERROR_STATUS, summary=f"bazel exit {code}", log=bazel_errors(out))


def flakes_check(wt: str, changed: list[str]) -> CheckResult:
    files = [p for p in changed if os.path.exists(os.path.join(wt, p))]
    if not files:
        return CheckResult("flakes", SKIP_STATUS, summary="no changed files")
    expr = "tests(rdeps(//..., set({})))".format(" ".join(files))
    code, out = bazel(wt, "query", "--keep_going", "--output=label", expr)
    targets = sorted(line.strip() for line in out.splitlines() if line.startswith("//"))
    if not targets:
        return CheckResult("flakes", SKIP_STATUS, summary="no test depends on the changed files")
    result = bazel_check(
        "flakes", wt, "test", *targets, "--config=verify", "--runs_per_test=5", "--nocache_test_results"
    )
    result.summary = f"{len(targets)} affected test target(s) x5: " + result.summary
    return result


def default_base(repo: str) -> str:
    for candidate in ("origin/master", "master", "origin/main", "main"):
        try:
            gitutil.rev(repo, candidate)
            return candidate
        except RuntimeError:
            continue
    return "master"


def write_report(repo: str, report: Report) -> str:
    out_dir = os.path.join(repo, ".verify", "reports")
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.join(out_dir, f"{report.sha[:12]}{'-fast' if report.mode == '--fast' else ''}")
    with open(stem + ".json", "w", encoding="utf-8") as f:
        f.write(report.to_json() + "\n")
    with open(stem + ".md", "w", encoding="utf-8") as f:
        f.write(render_markdown(report))
    return stem


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/verify", description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fast", action="store_true", help="the inner loop: working tree, no git checks")
    mode.add_argument("--deep", action="store_true", help="the gate plus flake re-runs of affected tests")
    parser.add_argument("--base", help="base ref (default: origin/master, then master)")
    parser.add_argument("--json", action="store_true", help="print the JSON report instead of text")
    parser.add_argument("--repo", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    repo = args.repo or gitutil.git(os.getcwd(), "rev-parse", "--show-toplevel").strip()
    try:
        if args.fast:
            report = run_fast(repo)
        else:
            report = run_gate(repo, args.base or default_base(repo), args.deep)
    except Exception as e:
        sha = gitutil.git(repo, "rev-parse", "HEAD", check=False).strip() or "0" * 40
        report = Report(mode="--fast" if args.fast else "gate", sha=sha, base=args.base or "")
        report.checks.append(CheckResult("verify", ERROR_STATUS, summary=f"{type(e).__name__}: {e}"))
    stem = write_report(repo, report)
    print(report.to_json() if args.json else render_text(report))
    if not args.json:
        print(f"report: {os.path.relpath(stem, repo)}.md")
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
