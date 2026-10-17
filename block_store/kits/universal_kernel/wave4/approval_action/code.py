"""Neutral approval-action primitives.

A lightweight multi-eye approval mechanism for sensitive actions. Approvals are
scoped to a principal/action pair, expire automatically, and are consumed once.
Every lifecycle event is appended to the audit-evidence chain.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from block_store.kits.universal_kernel.wave1.audit_evidence import record as audit_record


class ApprovalDeniedError(Exception):
    """Raised when an approval is missing, expired, revoked, or insufficient."""


class ApprovalRequest:
    """A single pending/approved/consumed approval request."""

    def __init__(
        self,
        action_id: str,
        principal_id: str,
        scope: Dict[str, Any],
        payload: Dict[str, Any],
        expires_in_seconds: int = 3600,
    ) -> None:
        self.token = f"apr_{uuid.uuid4().hex}"
        self.action_id = action_id
        self.principal_id = principal_id
        self.scope = dict(scope)
        self.payload = dict(payload)
        self.expires_in_seconds = int(expires_in_seconds)
        self.required_approvers = 1
        self.approvers: List[str] = []
        self.status = "pending"
        self.created_at = datetime.now(timezone.utc)
        self.expires_at = self.created_at + timedelta(seconds=self.expires_in_seconds)
        self.consumed_at: Optional[datetime] = None

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token": self.token,
            "action_id": self.action_id,
            "principal_id": self.principal_id,
            "scope": self.scope,
            "payload": self.payload,
            "status": self.status,
            "required_approvers": self.required_approvers,
            "approvers": list(self.approvers),
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "consumed_at": self.consumed_at.isoformat() if self.consumed_at else None,
        }


class ApprovalStore:
    """In-memory approval store with an optional persistence stub."""

    def __init__(self, persistence: Optional[Any] = None) -> None:
        self._by_token: Dict[str, ApprovalRequest] = {}
        self._persistence = persistence

    def _save(self, request: ApprovalRequest) -> None:
        if self._persistence is not None:
            self._persistence.save(request.to_dict())

    def add(self, request: ApprovalRequest) -> None:
        self._by_token[request.token] = request
        self._save(request)

    def get(self, token: str) -> Optional[ApprovalRequest]:
        return self._by_token.get(token)

    def remove(self, token: str) -> None:
        self._by_token.pop(token, None)

    def reset(self) -> None:
        self._by_token.clear()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(
    event_type: str,
    request: ApprovalRequest,
    principal_id: str,
    outcome: str,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    audit_record(
        event_type=event_type,
        principal={"id": principal_id},
        scope=request.scope,
        action=request.action_id,
        outcome=outcome,
        payload={
            "approval_token": request.token,
            "action_id": request.action_id,
            "required_approvers": request.required_approvers,
            "approvers": list(request.approvers),
            "status": request.status,
            **(extra or {}),
        },
    )


def request_approval(
    action_id: str,
    principal_id: str,
    scope: Dict[str, Any],
    payload: Dict[str, Any],
    required_approvers: int = 1,
    expires_in_seconds: int = 3600,
    store: Optional[ApprovalStore] = None,
) -> str:
    """Create a pending approval and return its token."""
    request = ApprovalRequest(
        action_id=action_id,
        principal_id=principal_id,
        scope=scope,
        payload=payload,
        expires_in_seconds=expires_in_seconds,
    )
    if required_approvers < 1:
        raise ApprovalDeniedError("required_approvers must be at least 1")
    request.required_approvers = required_approvers
    target = store or _default_store
    target.add(request)
    _audit("approval_created", request, principal_id, "pending")
    return request.token


def approve(approval_token: str, approver_principal_id: str, store: Optional[ApprovalStore] = None) -> ApprovalRequest:
    """Record an approval from ``approver_principal_id``."""
    target = store or _default_store
    request = target.get(approval_token)
    if request is None:
        raise ApprovalDeniedError("approval not found")
    if request.status == "revoked":
        _audit("approval_denied", request, approver_principal_id, "revoked", {"reason": "revoked"})
        raise ApprovalDeniedError("approval has been revoked")
    if request.is_expired():
        request.status = "expired"
        target._save(request)
        _audit("approval_denied", request, approver_principal_id, "expired", {"reason": "expired"})
        raise ApprovalDeniedError("approval has expired")
    if request.status == "consumed":
        _audit("approval_denied", request, approver_principal_id, "consumed", {"reason": "already consumed"})
        raise ApprovalDeniedError("approval already consumed")
    if approver_principal_id in request.approvers:
        _audit("approval_denied", request, approver_principal_id, "duplicate", {"reason": "already approved"})
        raise ApprovalDeniedError("approver has already approved")
    request.approvers.append(approver_principal_id)
    if len(request.approvers) >= request.required_approvers:
        request.status = "approved"
    target._save(request)
    _audit("approval_approved", request, approver_principal_id, request.status)
    return request


def consume_approval(
    approval_token: str,
    action_id: str,
    store: Optional[ApprovalStore] = None,
) -> Dict[str, Any]:
    """Validate and consume an approved, unexpired, matching approval."""
    target = store or _default_store
    request = target.get(approval_token)
    if request is None:
        raise ApprovalDeniedError("approval not found")
    if request.action_id != action_id:
        _audit("approval_denied", request, "consumer", "mismatched", {"expected_action": action_id})
        raise ApprovalDeniedError("approval action mismatch")
    if request.status == "revoked":
        _audit("approval_denied", request, "consumer", "revoked", {"reason": "revoked"})
        raise ApprovalDeniedError("approval has been revoked")
    if request.is_expired():
        request.status = "expired"
        target._save(request)
        _audit("approval_denied", request, "consumer", "expired", {"reason": "expired"})
        raise ApprovalDeniedError("approval has expired")
    if request.status == "consumed":
        _audit("approval_denied", request, "consumer", "consumed", {"reason": "already consumed"})
        raise ApprovalDeniedError("approval already consumed")
    if request.status != "approved":
        _audit("approval_denied", request, "consumer", "insufficient", {"reason": "not approved"})
        raise ApprovalDeniedError("approval has not been approved")
    request.status = "consumed"
    request.consumed_at = _now()
    target._save(request)
    _audit("approval_consumed", request, "consumer", "consumed")
    return {
        "consumed": True,
        "scope": request.scope,
        "payload": request.payload,
    }


def get_status(approval_token: str, store: Optional[ApprovalStore] = None) -> Optional[Dict[str, Any]]:
    """Return the current approval status, or None if unknown."""
    target = store or _default_store
    request = target.get(approval_token)
    if request is None:
        return None
    if request.is_expired() and request.status not in ("consumed", "revoked"):
        request.status = "expired"
        target._save(request)
    return request.to_dict()


def reset_default_store() -> None:
    """Reset the module-level default store (tests only)."""
    _default_store.reset()


_default_store = ApprovalStore()
