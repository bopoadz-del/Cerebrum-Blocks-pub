"""ST-AWS-OIDC: deploy-aws.yml authenticates to AWS through GitHub OIDC
(role-to-assume), never through long-lived access-key secrets."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/deploy-aws.yml"
ROLE = "arn:aws:iam::059020085816:role/gh-store-deploy"

KEY_INPUT = re.compile(r"aws-(?:access-key-id|secret-access-key|session-token)\s*:")
SECRET_REF = re.compile(r"secrets\.AWS_[A-Za-z0-9_]*")


def static_key_refs(text: str) -> list:
    """Every access-key input or secrets.AWS_* reference in a workflow text."""
    return KEY_INPUT.findall(text) + SECRET_REF.findall(text)


def has_id_token_write(text: str) -> bool:
    doc = yaml.safe_load(text)
    scopes = [doc.get("permissions") or {}] + [
        (job or {}).get("permissions") or {} for job in (doc.get("jobs") or {}).values()
    ]
    return any(isinstance(p, dict) and p.get("id-token") == "write" for p in scopes)


def aws_credentials_step(text: str) -> dict:
    doc = yaml.safe_load(text)
    for job in doc["jobs"].values():
        for step in job.get("steps", []):
            if str(step.get("uses", "")).startswith("aws-actions/configure-aws-credentials"):
                return step.get("with") or {}
    raise AssertionError("no configure-aws-credentials step")


def test_no_static_aws_keys_in_deploy_workflow():
    assert static_key_refs(WORKFLOW.read_text(encoding="utf-8")) == []


def test_deploy_workflow_grants_id_token_write():
    assert has_id_token_write(WORKFLOW.read_text(encoding="utf-8"))


def test_credentials_step_assumes_the_deploy_role_in_env_region():
    w = aws_credentials_step(WORKFLOW.read_text(encoding="utf-8"))
    assert w.get("role-to-assume") == ROLE
    assert w.get("aws-region") == "${{ env.AWS_REGION }}"


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
