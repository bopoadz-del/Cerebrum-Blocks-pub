"""End-to-end integration test for the Wave 1 + Wave 4 trust chain."""

from pathlib import Path

import pytest

from block_store.kits.universal_kernel.wave1.audit_evidence import (
    AuditIntegrityError,
    record,
    reset_audit_log,
    verify_chain,
)
from block_store.kits.universal_kernel.wave1.audit_evidence.code import _default_log
from block_store.kits.universal_kernel.wave1.authorization_policy import (
    load_policy,
    permitted,
    reset_policy,
)
from block_store.kits.universal_kernel.wave1.identity import (
    authenticate_principal,
    issue_token,
    register_principal,
    reset_identity_store,
    verify_token,
)
from block_store.kits.universal_kernel.wave1.provenance_verification import (
    ProvenanceMismatch,
    build_provenance,
    verify_kit,
)
from block_store.kits.universal_kernel.wave1.rate_limit_guard import (
    RateLimiter,
    reset_rate_limiter,
)
from block_store.kits.universal_kernel.wave1.scope_guard import (
    ScopeViolation,
    assert_in_scope,
)
from block_store.kits.universal_kernel.wave4.approval_action import (
    approve,
    consume_approval,
    request_approval,
    reset_default_store,
)
from block_store.kits.universal_kernel.wave4.block_runner import BlockEnvelope, BlockRunner


TENANT = "t-1"
PROJECT = "p-1"
ROLE = "admin"
PASSWORD = "SecurePass1"
PRINCIPAL_ID = "principal-1"
SECRET = __import__("secrets").token_urlsafe(32)


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_identity_store()
    reset_policy()
    reset_audit_log()
    reset_rate_limiter()
    reset_default_store()
    yield
    reset_identity_store()
    reset_policy()
    reset_audit_log()
    reset_rate_limiter()
    reset_default_store()


def _echo_handler(arguments):
    return {"echoed": arguments.get("message")}


def test_trust_chain_end_to_end():
    # 1. Register a principal with password, tenant, project, and role.
    principal = register_principal(
        password=PASSWORD,
        principal_id=PRINCIPAL_ID,
        tenant_ids=[TENANT],
        project_ids=[PROJECT],
        roles=[ROLE],
    )
    assert principal.id == PRINCIPAL_ID
    assert principal.tenant_ids == [TENANT]
    assert principal.project_ids == [PROJECT]
    assert principal.roles == [ROLE]

    # 2. Authenticate and issue a token.
    authenticated = authenticate_principal(PRINCIPAL_ID, PASSWORD)
    token = issue_token(authenticated, secret=SECRET, expires_in=300)
    assert isinstance(token, str) and token

    # 3. Verify token yields principal payload.
    payload = verify_token(token, secret=SECRET)
    assert payload["principal_id"] == PRINCIPAL_ID
    assert payload["tenant_ids"] == [TENANT]
    assert payload["project_ids"] == [PROJECT]
    assert payload["roles"] == [ROLE]

    # 4. Authorization policy permits resource.delete for admin role.
    load_policy(
        {
            "roles": {
                ROLE: {
                    "permissions": [
                        {"action": "resource.delete", "resource": "*", "effect": "allow"}
                    ]
                }
            }
        }
    )
    authz = permitted(
        {"roles": [ROLE]},
        action="resource.delete",
        resource="some-resource-id",
    )
    assert authz["allowed"] is True
    assert ROLE in authz["matched_roles"]

    # 5. Scope guard allows t-1/p-1; cross-tenant t-2 raises ScopeViolation.
    principal_payload = {
        "id": PRINCIPAL_ID,
        "tenant_ids": [TENANT],
        "project_ids": [PROJECT],
    }
    assert_in_scope(principal_payload, tenant_id=TENANT, project_id=PROJECT)
    with pytest.raises(ScopeViolation):
        assert_in_scope(principal_payload, tenant_id="t-2", project_id=PROJECT)

    # 6. Rate-limit guard allows first 3 calls, then blocks the 4th.
    limiter = RateLimiter()
    action = "resource.delete"
    for i in range(3):
        result = limiter.record_and_check(
            identity=PRINCIPAL_ID,
            action=action,
            window_seconds=1.0,
            max_requests=3,
        )
        assert result["allowed"] is True, f"call {i + 1} should be allowed"
    blocked = limiter.record_and_check(
        identity=PRINCIPAL_ID,
        action=action,
        window_seconds=1.0,
        max_requests=3,
    )
    assert blocked["allowed"] is False
    assert blocked["remaining"] == 0

    # 7. Block runner executes echo after approval is requested and consumed.
    approval_token = request_approval(
        action_id="echo:run",
        principal_id=PRINCIPAL_ID,
        scope={"tenant_id": TENANT, "project_id": PROJECT},
        payload={"reason": "trust-chain integration test"},
        required_approvers=1,
        expires_in_seconds=300,
    )
    assert approval_token.startswith("apr_")
    approve(approval_token, approver_principal_id="approver-1")
    consumed = consume_approval(approval_token, action_id="echo:run")
    assert consumed["consumed"] is True

    runner = BlockRunner(
        allowlist=["echo"],
        registry={"echo": _echo_handler},
    )
    envelope = BlockEnvelope(
        command="echo",
        arguments={"message": "hello universal kernel"},
        principal=principal_payload,
        scope={"tenant_id": TENANT, "project_id": PROJECT},
    )
    outcome = runner.run(envelope)
    assert outcome.status.value == "success"
    assert outcome.data["echoed"] == "hello universal kernel"

    # 8. Audit evidence chain records approval create, consume, and block run.
    audit_records = _default_log.records()
    event_types = [r["event_type"] for r in audit_records]
    assert "approval_created" in event_types
    assert "approval_consumed" in event_types
    assert "block_executed" in event_types

    # 9. Verify audit chain integrity.
    assert verify_chain(audit_records) is True

    # 10. Tamper with one audit record hash; verify AuditIntegrityError.
    tampered_records = [dict(r) for r in audit_records]
    tampered_records[0]["record_hash"] = "0" * 64
    with pytest.raises(AuditIntegrityError):
        verify_chain(tampered_records)

    # 11. Tamper with top-level manifest and verify provenance mismatch.
    root = Path(__file__).resolve().parents[2]
    uk_dir = root / "block_store" / "kits" / "universal_kernel"
    manifest_file = uk_dir / "manifest.json"
    provenance_path = uk_dir / "provenance.json"
    original_bytes = manifest_file.read_bytes()
    try:
        if provenance_path.exists():
            provenance_path.unlink()
        build_provenance(uk_dir, output_name="provenance.json")
        assert verify_kit(provenance_path) is True

        # Append a byte to the manifest.
        manifest_file.write_bytes(original_bytes + b"\n")
        with pytest.raises(ProvenanceMismatch):
            verify_kit(provenance_path)
    finally:
        manifest_file.write_bytes(original_bytes)
        if provenance_path.exists():
            provenance_path.unlink()
