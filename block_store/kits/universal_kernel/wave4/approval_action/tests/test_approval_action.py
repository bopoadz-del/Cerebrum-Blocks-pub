"""Tests for the neutral approval-action sub-kit."""

import pytest

from block_store.kits.universal_kernel.wave1.audit_evidence import reset_audit_log
from block_store.kits.universal_kernel.wave1.audit_evidence.code import (
    _default_log as audit_log,
)
from block_store.kits.universal_kernel.wave4.approval_action import (
    ApprovalDeniedError,
    ApprovalStore,
    approve,
    consume_approval,
    get_status,
    request_approval,
    reset_default_store,
)


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_audit_log()
    reset_default_store()
    yield
    reset_audit_log()
    reset_default_store()


PRINCIPAL_ID = "principal-1"
APPROVER_ID = "approver-1"
ACTION_ID = "action-1"
SCOPE = {"tenant_id": "tenant-1", "project_id": "project-1"}
PAYLOAD = {"resource": "resource-1"}


def test_request_approve_and_consume():
    token = request_approval(
        action_id=ACTION_ID,
        principal_id=PRINCIPAL_ID,
        scope=SCOPE,
        payload=PAYLOAD,
    )
    assert token.startswith("apr_")

    approve(token, APPROVER_ID)
    status = get_status(token)
    assert status["status"] == "approved"

    result = consume_approval(token, ACTION_ID)
    assert result["consumed"] is True
    assert result["scope"] == SCOPE
    assert result["payload"] == PAYLOAD

    status = get_status(token)
    assert status["status"] == "consumed"


def test_expired_approval_is_denied():
    token = request_approval(
        action_id=ACTION_ID,
        principal_id=PRINCIPAL_ID,
        scope=SCOPE,
        payload=PAYLOAD,
        expires_in_seconds=-1,
    )
    with pytest.raises(ApprovalDeniedError, match="expired"):
        approve(token, APPROVER_ID)


def test_mismatched_action_is_denied():
    token = request_approval(
        action_id=ACTION_ID,
        principal_id=PRINCIPAL_ID,
        scope=SCOPE,
        payload=PAYLOAD,
    )
    approve(token, APPROVER_ID)
    with pytest.raises(ApprovalDeniedError, match="mismatch"):
        consume_approval(token, "other-action")


def test_unapproved_consume_is_denied():
    token = request_approval(
        action_id=ACTION_ID,
        principal_id=PRINCIPAL_ID,
        scope=SCOPE,
        payload=PAYLOAD,
    )
    with pytest.raises(ApprovalDeniedError, match="not been approved"):
        consume_approval(token, ACTION_ID)


def test_audit_evidence_recorded():
    before = len(audit_log.records())
    request_approval(
        action_id=ACTION_ID,
        principal_id=PRINCIPAL_ID,
        scope=SCOPE,
        payload=PAYLOAD,
    )
    records = audit_log.records()
    assert len(records) == before + 1
    assert records[-1]["event_type"] == "approval_created"


def test_custom_store_isolation():
    store = ApprovalStore()
    token = request_approval(
        action_id=ACTION_ID,
        principal_id=PRINCIPAL_ID,
        scope=SCOPE,
        payload=PAYLOAD,
        store=store,
    )
    assert get_status(token, store=store) is not None
    assert get_status(token) is None
