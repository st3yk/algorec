"""Self-tests for the GitHub configuration: the master ruleset and the verify workflow.
See docs/guardrails.md."""

import json
import os
import re

import pytest

ROOT = os.path.join(os.environ.get("TEST_SRCDIR", ""), "_main")


def read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_the_ruleset_protects_master_and_lets_the_admin_bypass_only_through_a_pr():
    ruleset = json.loads(read("tools/github/ruleset.json"))
    assert ruleset["target"] == "branch" and ruleset["enforcement"] == "active"
    assert ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert ruleset["bypass_actors"] == [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}]
    rules = {r["type"]: r.get("parameters", {}) for r in ruleset["rules"]}
    assert {"deletion", "non_fast_forward", "required_linear_history", "pull_request"} <= set(rules)
    checks = rules["required_status_checks"]
    assert checks["strict_required_status_checks_policy"] is True
    assert checks["required_status_checks"] == [{"context": "verify", "integration_id": 15368}]


WORKFLOW = ".github/workflows/verify.yml"


def test_every_action_is_pinned_to_a_commit():
    uses = re.findall(r"uses:\s*(\S+)", read(WORKFLOW))
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u) for u in uses), uses


def test_the_workflow_is_read_only_and_names_the_required_check():
    text = read(WORKFLOW)
    assert re.search(r"^permissions:\n  contents: read\n", text, re.M)
    assert "write" not in text.split("jobs:")[0]
    assert re.search(r"^  verify:\n", text, re.M)


@pytest.mark.parametrize("forbidden", ["HEAD~1", "--judge", "secrets.", "tools/verify --base"])
def test_the_workflow_never_judges_against_its_own_history_or_uses_secrets(forbidden):
    assert forbidden not in read(WORKFLOW)


def test_a_base_without_a_judge_is_skipped_not_judged_by_the_branch():
    text = read(WORKFLOW)
    assert 'echo "code=skip"' in text and "skip) echo" in text


def test_the_workflow_extracts_the_judge_from_the_merge_base():
    text = read(WORKFLOW)
    assert 'git merge-base "$BASE" HEAD' in text and "git archive" in text
    assert "python3 -m tools.verify_lib.verify" in text


GATEKEEPER = ".github/workflows/gatekeeper.yml"


def job(text: str, name: str) -> str:
    start = text.index(f"\n  {name}:\n")
    rest = text[start + 1 :]
    following = re.search(r"\n  [a-z]+:\n", rest[len(name) + 3 :])
    return rest[: following.start() + len(name) + 3] if following else rest


def test_prs_are_judged_only_by_the_gatekeeper_from_the_default_branch():
    assert "pull_request:" not in read(WORKFLOW)
    text = read(GATEKEEPER)
    assert re.search(r"^on:\n  pull_request_target:\n", text, re.M)
    assert re.search(r"^permissions: \{\}\n", text, re.M)


def test_the_judging_job_is_read_only_and_leaves_no_credentials_or_caches():
    verify = job(read(GATEKEEPER), "verify")
    assert "    permissions:\n      contents: read\n" in verify and "write" not in verify
    assert "persist-credentials: false" in verify and "cache-save: false" in verify
    assert "ref: ${{ github.event.pull_request.head.sha }}" in verify
    assert 'git merge-base "$BASE" HEAD' in verify and "tools/verify --base" not in verify


def test_the_writing_job_never_touches_the_prs_code():
    enforce = job(read(GATEKEEPER), "enforce")
    assert "pull-requests: write" in enforce
    for forbidden in ("actions/checkout", "bazel ", "verify_lib", "python3", "git ", "bash ", "./"):
        assert forbidden not in enforce, forbidden
    assert "gh pr ready" in enforce and "--undo" in enforce and "--add-label needs-human" in enforce


def test_every_gatekeeper_action_is_pinned_to_a_commit():
    uses = re.findall(r"uses:\s*(\S+)", read(GATEKEEPER))
    assert uses and all(re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", u) for u in uses), uses


@pytest.mark.parametrize("workflow", [WORKFLOW, GATEKEEPER])
def test_the_extracted_judge_runs_from_its_own_directory(workflow):
    text = read(workflow)
    runs = re.findall(r"^( *)(.*python3 -m tools\.verify_lib\.verify.*)$", text, re.M)
    assert runs and all('(cd "$judge" && ' in line for _, line in runs), runs


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
