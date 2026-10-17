"""Approval matrix engine (kernel component).

Decides approval from action + role + value/risk threshold + payload
digest. Enforces: self-approval refusal, segregation of duties, payload
binding (the approval is bound to a digest of the payload it approved),
expiry, replay prevention, and audited emergency override. The LLM
cannot authorize anything; it can only request an approval.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

from app.reasoning_kernel import ReasoningResult, ReasoningStatus
from app.reasoning_kernel.schemas import ApprovalPolicySpec


class ApprovalRequired(Exception):
    """Raised by ``check`` when an approval is required but absent."""

    def __init__(self, policy: ApprovalPolicySpec, reason: str):
        self.policy = policy
        self.reason = reason
        super().__init__(reason)


class ApprovalRefused(Exception):
    """Raised when an approval request is refused (named reason)."""


def payload_digest(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ApprovalMatrixEngine:
    def __init__(self, policies: Optional[List[ApprovalPolicySpec]] = None) -> None:
        self._policies: Dict[str, ApprovalPolicySpec] = {}
        for policy in policies or []:
            self.add(policy)
        self._issued: Dict[str, Dict[str, Any]] = {}  # token -> record
        self._audit: List[Dict[str, Any]] = []

    def add(self, policy: ApprovalPolicySpec) -> None:
        self._policies[policy.action] = policy

    def policy_for(self, action: str) -> Optional[ApprovalPolicySpec]:
        return self._policies.get(action)

    def check(
        self,
        action: str,
        requester: Dict[str, Any],
        payload: Dict[str, Any],
        *,
        value: Optional[float] = None,
        approvals: Optional[List[Dict[str, Any]]] = None,
        domain: str = "",
        intent: str = "",
    ) -> ReasoningResult:
        """Decide whether the action may proceed. Never authorizes: a
        required-but-absent approval yields APPROVAL_REQUIRED."""
        policy = self._policies.get(action)
        if policy is None:
            return ReasoningResult(
                status=ReasoningStatus.UNSUPPORTED,
                domain=domain,
                intent=intent,
                explanation=f"no approval policy for action {action!r}",
            ).stamp_digests()

        requester_role = requester.get("role") or ""
        if policy.requester_roles and requester_role not in policy.requester_roles:
            return ReasoningResult(
                status=ReasoningStatus.PERMISSION_DENIED,
                domain=domain,
                intent=intent,
                explanation=f"{action}: role {requester_role!r} may not request this action",
            ).stamp_digests()

        # Threshold escalation by value/risk.
        tier = _risk_tier(policy, value)
        if not _needs_approval(policy, tier):
            return ReasoningResult(
                status=ReasoningStatus.SUCCESS,
                domain=domain,
                intent=intent,
                approval={"required": False, "action": action, "risk_tier": tier},
                explanation=f"{action}: below approval threshold ({tier})",
            ).stamp_digests()

        provided = approvals or []
        valid: List[Dict[str, Any]] = []
        seen_approvers: set = set()
        for entry in provided:
            try:
                rec = self._validate_approval(policy, entry, payload)
            except ApprovalRefused as exc:
                self._audit.append({"action": action, "event": "refused", "reason": str(exc), "at": time.time()})
                continue
            if rec["approver_id"] in seen_approvers:
                continue
            seen_approvers.add(rec["approver_id"])
            valid.append(rec)

        if len(valid) < policy.minimum_approvals:
            return ReasoningResult(
                status=ReasoningStatus.APPROVAL_REQUIRED,
                domain=domain,
                intent=intent,
                approval={
                    "required": True,
                    "action": action,
                    "risk_tier": tier,
                    "valid_approvals": len(valid),
                    "minimum_approvals": policy.minimum_approvals,
                    "approver_roles": policy.approver_roles,
                },
                explanation=f"{action}: {len(valid)}/{policy.minimum_approvals} valid approvals",
            ).stamp_digests()

        return ReasoningResult(
            status=ReasoningStatus.SUCCESS,
            domain=domain,
            intent=intent,
            approval={"required": True, "action": action, "risk_tier": tier, "granted": True},
            evidence=[{"kind": "approval", "approvers": [v["approver_id"] for v in valid]}],
            explanation=f"{action}: approved by {len(valid)} approver(s)",
        ).stamp_digests()

    def issue(
        self,
        action: str,
        *,
        approver: Dict[str, Any],
        payload: Dict[str, Any],
        ttl_seconds: Optional[int] = None,
    ) -> str:
        """Mint an approval token bound to the payload digest."""
        policy = self._policies.get(action)
        if policy is None:
            raise ApprovalRefused(f"no approval policy for action {action!r}")
        approver_role = approver.get("role") or ""
        if policy.approver_roles and approver_role not in policy.approver_roles:
            raise ApprovalRefused(f"{action}: role {approver_role!r} cannot approve")
        if policy.self_approval == "prohibited" and approver.get("id") == approver.get("requester_id"):
            raise ApprovalRefused(f"{action}: self-approval prohibited")
        token = "appr_" + secrets.token_urlsafe(24)
        self._issued[token] = {
            "action": action,
            "approver_id": approver.get("id"),
            "approver_role": approver_role,
            "digest": payload_digest(payload),
            "issued_at": time.time(),
            "expires_at": (
                time.time() + (ttl_seconds or policy.expiry_seconds)
                if (ttl_seconds or policy.expiry_seconds)
                else None
            ),
            "consumed": False,
        }
        self._audit.append({"action": action, "event": "issued", "approver": approver.get("id"), "at": time.time()})
        return token

    def emergency_override(
        self, action: str, *, admin: Dict[str, Any], payload: Dict[str, Any], justification: str
    ) -> ReasoningResult:
        policy = self._policies.get(action)
        if policy is None:
            return ReasoningResult(status=ReasoningStatus.UNSUPPORTED, explanation=f"no policy for {action!r}").stamp_digests()
        override = policy.emergency_override or {}
        role = override.get("role")
        if not role or admin.get("role") != role:
            return ReasoningResult(
                status=ReasoningStatus.PERMISSION_DENIED,
                explanation=f"emergency override requires role {role!r}",
            ).stamp_digests()
        if override.get("justification_required") and not justification:
            return ReasoningResult(
                status=ReasoningStatus.DEPENDENCY_REQUIRED,
                missing_inputs=["justification"],
                explanation="emergency override requires justification",
            ).stamp_digests()
        self._audit.append(
            {
                "action": action,
                "event": "emergency_override",
                "admin": admin.get("id"),
                "justification": justification,
                "digest": payload_digest(payload),
                "at": time.time(),
            }
        )
        return ReasoningResult(
            status=ReasoningStatus.SUCCESS,
            approval={"required": True, "action": action, "emergency_override": True},
            evidence=[{"kind": "emergency_override", "justification": justification}],
            explanation=f"{action}: emergency override by {admin.get('id')}",
        ).stamp_digests()

    def audit_log(self) -> List[Dict[str, Any]]:
        return list(self._audit)

    # -- internal ---------------------------------------------------------

    def _validate_approval(self, policy: ApprovalPolicySpec, entry: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        token = str(entry.get("token") or "")
        record = self._issued.get(token)
        if record is None:
            raise ApprovalRefused("unknown approval token")
        if record["action"] != policy.action:
            raise ApprovalRefused("approval token is for a different action")
        if record.get("consumed"):
            raise ApprovalRefused("approval token already consumed (replay)")
        if record.get("expires_at") and time.time() > record["expires_at"]:
            raise ApprovalRefused("approval token expired")
        if policy.payload_binding == "required" and record["digest"] != payload_digest(payload):
            raise ApprovalRefused("payload does not match the approved digest")
        if policy.self_approval == "prohibited" and record["approver_id"] == entry.get("requester_id"):
            raise ApprovalRefused("self-approval prohibited")
        # Segregation of duties: no single approver may satisfy two roles
        # that the policy separates.
        for pair in policy.segregation_of_duties or []:
            if record["approver_id"] in pair and entry.get("requester_id") in pair:
                raise ApprovalRefused("segregation of duties violated")
        record["consumed"] = True
        return record


def _risk_tier(policy: ApprovalPolicySpec, value: Optional[float]) -> str:
    """Effective risk tier.

    A policy WITHOUT numeric thresholds stays at its declared tier — an
    empty threshold map must never degrade a high-risk action to low.
    With thresholds, the value can only ESCALATE the tier, never lower it.
    """
    thresholds = policy.thresholds or {}
    derived = "low"
    if value is not None:
        if "high" in thresholds and value >= float(thresholds["high"]):
            derived = "high"
        elif "medium" in thresholds and value >= float(thresholds["medium"]):
            derived = "medium"
        elif "low" in thresholds and value >= float(thresholds["low"]):
            derived = "low"
    order = {"low": 0, "medium": 1, "high": 2}
    return policy.risk_tier if order[policy.risk_tier] >= order[derived] else derived


def _needs_approval(policy: ApprovalPolicySpec, tier: str) -> bool:
    """Approval is required when the effective tier is at or above the
    policy's declared tier, or when the policy declares approver roles and
    the tier is not explicitly below the policy tier."""
    order = {"low": 0, "medium": 1, "high": 2}
    return order.get(tier, 0) >= order.get(policy.risk_tier, 1)
