"""ST-AWS-OIDC: deploy-aws.yml authenticates to AWS through GitHub OIDC with a
role taken from a repo variable, least-privilege job permissions, main-only
triggers, and no long-lived access-key secrets or account-id literals."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/deploy-aws.yml"
CI = ROOT / ".github/workflows/ci.yml"
ROLE_EXPR = "${{ vars.AWS_DEPLOY_ROLE_ARN }}"
JOB_PERMISSIONS = {"id-token": "write", "contents": "read"}
MAIN_ONLY = "github.ref == 'refs/heads/main'"

KEY_INPUT = re.compile(r"aws-(?:access-key-id|secret-access-key|session-token)\s*:")
SECRET_REF = re.compile(r"secrets\.AWS_[A-Za-z0-9_]*")
BARE_ACCOUNT_ID = re.compile(r"(?<![0-9])[0-9]{12}(?![0-9])")
ARN_ACCOUNT_ID = re.compile(r"arn:aws[a-z-]*:[a-z0-9-]*:[a-z0-9-]*:([0-9]{12})")


def _load(text: str) -> dict:
    doc = yaml.safe_load(text)
    if True in doc:  # PyYAML reads the bare key `on` as boolean True
        doc["on"] = doc.pop(True)
    return doc


def static_key_refs(text: str) -> list:
    """Every access-key input or secrets.AWS_* reference in a workflow text."""
    return KEY_INPUT.findall(text) + SECRET_REF.findall(text)


def account_id_literals(text: str, workflow: bool) -> list:
    """12-digit account ids: any bare one in a workflow, ARN-embedded in tests."""
    return BARE_ACCOUNT_ID.findall(text) if workflow else ARN_ACCOUNT_ID.findall(text)


def has_id_token_write(text: str) -> bool:
    doc = _load(text)
    scopes = [doc.get("permissions") or {}] + [
        (job or {}).get("permissions") or {} for job in (doc.get("jobs") or {}).values()
    ]
    return any(isinstance(p, dict) and p.get("id-token") == "write" for p in scopes)


def permission_errors(text: str, job: str = "deploy") -> list:
    doc = _load(text)
    errs = []
    if "permissions" in doc:
        errs.append("workflow-level permissions present")
    got = (doc.get("jobs") or {}).get(job, {}).get("permissions")
    if got != JOB_PERMISSIONS:
        errs.append(f"job permissions {got!r} != {JOB_PERMISSIONS!r}")
    return errs


def trigger_errors(text: str) -> list:
    on = _load(text).get("on")
    errs = []
    if not isinstance(on, dict) or set(on) != {"push", "workflow_dispatch"}:
        errs.append(f"triggers {sorted(on) if isinstance(on, dict) else on!r}")
        return errs
    if on["push"] != {"branches": ["main"]}:
        errs.append(f"push filter {on['push']!r}")
    return errs


def aws_credentials_step(text: str) -> dict:
    for job in _load(text)["jobs"].values():
        for step in job.get("steps", []):
            if str(step.get("uses", "")).startswith("aws-actions/configure-aws-credentials"):
                return step.get("with") or {}
    raise AssertionError("no configure-aws-credentials step")


# --- the real workflow ------------------------------------------------------

def _wf() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_no_static_aws_keys_in_deploy_workflow():
    assert static_key_refs(_wf()) == []


def test_deploy_workflow_grants_id_token_write():
    assert has_id_token_write(_wf())


def test_deploy_permissions_are_exactly_job_scoped_least_privilege():
    assert permission_errors(_wf()) == []


def test_deploy_triggers_are_exactly_push_main_and_dispatch():
    assert trigger_errors(_wf()) == []


def test_deploy_job_runs_only_on_main():
    assert _load(_wf())["jobs"]["deploy"].get("if") == MAIN_ONLY


def test_credentials_step_takes_role_from_repo_variable():
    w = aws_credentials_step(_wf())
    assert w.get("role-to-assume") == ROLE_EXPR
    assert w.get("aws-region") == "${{ env.AWS_REGION }}"


def test_no_account_id_literal_in_workflows_or_tests():
    hits = []
    for p in sorted((ROOT / ".github/workflows").glob("*.y*ml")):
        hits += [f"{p.name}: {m}" for m in account_id_literals(p.read_text(encoding="utf-8"), True)]
    for p in sorted((ROOT / "tests").rglob("*.py")):
        hits += [f"{p.name}: {m}" for m in account_id_literals(p.read_text(encoding="utf-8"), False)]
    assert hits == []


def test_ci_runs_this_pin_in_a_named_step():
    steps = [s for j in _load(CI.read_text(encoding="utf-8"))["jobs"].values() for s in j.get("steps", [])]
    assert any(
        s.get("name") and "tests/test_deploy_aws_oidc.py" in str(s.get("run", "")) for s in steps
    )


# --- detectors, two inputs each ---------------------------------------------

def _synthetic_account() -> str:
    return "".join(str((i * 7 + 3) % 10) for i in range(12))  # built at runtime


@pytest.mark.parametrize(
    "text, found",
    [
        ("with:\n  role-to-assume: arn:x\n  aws-region: us-west-2\n", []),
        ("with:\n  aws-access-key-id: ${{ secrets.AWS_KEY_ONE }}\n", ["aws-access-key-id:", "secrets.AWS_KEY_ONE"]),
        ("env:\n  X: ${{ secrets.AWS_OTHER }}\n", ["secrets.AWS_OTHER"]),
    ],
)
def test_static_key_detector_two_inputs(text, found):
    assert static_key_refs(text) == found


def test_account_id_detector_two_inputs():
    acct = _synthetic_account()
    assert account_id_literals(f"role-to-assume: arn:aws:iam::{acct}:role/r\n", True) == [acct]
    assert account_id_literals(f'ROLE = "arn:aws:iam::{acct}:role/r"\n', False) == [acct]
    assert account_id_literals(f"role-to-assume: {ROLE_EXPR}\n", True) == []
    # bare id outside any ARN (an ECR registry host) is still caught in a workflow
    assert account_id_literals(f"image: {acct}.dkr.ecr.us-west-2.amazonaws.com/x:1\n", True) == [acct]
    other = _synthetic_account()[::-1]
    assert account_id_literals(f"REGISTRY: {other}.dkr.ecr.eu-west-1.amazonaws.com\n", True) == [other]
    assert account_id_literals('ROLE = "${{ vars.X }}"\nTS = 1234567890123\n', False) == []


@pytest.mark.parametrize(
    "text, ok",
    [
        ("permissions:\n  id-token: write\njobs:\n  a: {}\n", True),
        ("jobs:\n  a:\n    permissions:\n      id-token: write\n", True),
        ("permissions:\n  contents: read\njobs:\n  a: {}\n", False),
        ("jobs:\n  a:\n    permissions:\n      id-token: read\n", False),
    ],
)
def test_id_token_detector_two_inputs(text, ok):
    assert has_id_token_write(text) is ok


GOOD_PERMS = "jobs:\n  deploy:\n    permissions:\n      id-token: write\n      contents: read\n"


@pytest.mark.parametrize(
    "text, n_errors",
    [
        (GOOD_PERMS, 0),
        ("permissions:\n  id-token: write\n" + GOOD_PERMS, 1),
        (GOOD_PERMS.replace("contents: read", "contents: write"), 1),
        (GOOD_PERMS + "      actions: write\n", 1),
        ("permissions:\n  id-token: write\n  contents: read\njobs:\n  deploy: {}\n", 2),
    ],
)
def test_permission_detector_two_inputs(text, n_errors):
    assert len(permission_errors(text)) == n_errors


@pytest.mark.parametrize(
    "text, n_errors",
    [
        ("on:\n  push:\n    branches: [main]\n  workflow_dispatch:\n", 0),
        ("on:\n  push:\n    branches: [main]\n  workflow_dispatch:\n  pull_request_target:\n", 1),
        ("on:\n  push:\n    branches: [main]\n  workflow_dispatch:\n  pull_request:\n", 1),
        ("on:\n  push:\n    branches: [main, dev]\n  workflow_dispatch:\n", 1),
    ],
)
def test_trigger_detector_two_inputs(text, n_errors):
    assert len(trigger_errors(text)) == n_errors
