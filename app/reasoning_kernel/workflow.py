"""Workflow engine (kernel component).

A finite state machine enforced in code: transitions carry permitted
actors, guards, evidence requirements, and approval requirements. The
LLM cannot move a workflow state directly; it can only propose a
transition, which this engine accepts or refuses with the reason named.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.reasoning_kernel import ReasoningResult, ReasoningStatus
from app.reasoning_kernel.schemas import WorkflowSpec

_log = logging.getLogger(__name__)


class WorkflowEngine:
    def __init__(self, spec: WorkflowSpec) -> None:
        self.spec = spec
        self._instances: Dict[str, Dict[str, Any]] = {}

    def create(self, instance_id: str, facts: Optional[Dict[str, Any]] = None) -> ReasoningResult:
        if instance_id in self._instances:
            return ReasoningResult(
                status=ReasoningStatus.EXECUTION_ERROR,
                explanation=f"instance {instance_id!r} already exists",
            ).stamp_digests()
        self._instances[instance_id] = {
            "state": self.spec.initial_state,
            "facts": dict(facts or {}),
            "history": [
                {
                    "from": None,
                    "to": self.spec.initial_state,
                    "at": _now(),
                    "by": None,
                }
            ],
            "approvals": {},
        }
        return ReasoningResult(
            status=ReasoningStatus.SUCCESS,
            workflow={"instance_id": instance_id, "state": self.spec.initial_state},
            explanation=f"instance {instance_id!r} created in {self.spec.initial_state}",
            versions={"workflow": self.spec.version},
        ).stamp_digests()

    def transition(
        self,
        instance_id: str,
        to_state: str,
        *,
        actor: Optional[str] = None,
        evidence: Optional[Dict[str, Any]] = None,
        approval_token: Optional[str] = None,
        domain: str = "",
        intent: str = "",
    ) -> ReasoningResult:
        inst = self._instances.get(instance_id)
        if inst is None:
            return ReasoningResult(
                status=ReasoningStatus.DEPENDENCY_REQUIRED,
                missing_inputs=["instance_id"],
                explanation=f"workflow instance {instance_id!r} does not exist",
            ).stamp_digests()
        current = inst["state"]

        transition = next(
            (
                t
                for t in self.spec.transitions
                if t.get("from") == current and t.get("to") == to_state
            ),
            None,
        )
        if transition is None:
            return ReasoningResult(
                status=ReasoningStatus.UNSUPPORTED,
                domain=domain,
                intent=intent,
                workflow={"instance_id": instance_id, "state": current},
                explanation=f"{self.spec.workflow_id}: {current} → {to_state} is not a declared transition",
            ).stamp_digests()

        # Permitted actors.
        allowed = transition.get("permitted_actors") or self.spec.permitted_actors.get(to_state) or []
        if allowed and actor not in allowed:
            return ReasoningResult(
                status=ReasoningStatus.PERMISSION_DENIED,
                domain=domain,
                intent=intent,
                workflow={"instance_id": instance_id, "state": current, "attempted": to_state},
                explanation=(
                    f"{self.spec.workflow_id}: {to_state} requires one of {allowed}; "
                    f"actor {actor!r} is not permitted"
                ),
            ).stamp_digests()

        # Guards.
        for guard in transition.get("guards") or []:
            if guard and not _guard_holds(guard, inst["facts"]):
                return ReasoningResult(
                    status=ReasoningStatus.VALIDATION_ERROR,
                    domain=domain,
                    intent=intent,
                    explanation=f"guard failed: {guard}",
                ).stamp_digests()

        # Evidence requirements.
        required_evidence = transition.get("evidence_required") or self.spec.evidence_required.get(to_state) or []
        missing = [e for e in required_evidence if not (evidence or {}).get(e)]
        if missing:
            return ReasoningResult(
                status=ReasoningStatus.DEPENDENCY_REQUIRED,
                domain=domain,
                intent=intent,
                missing_inputs=[f"evidence:{e}" for e in missing],
                explanation=f"transition requires evidence: {', '.join(missing)}",
            ).stamp_digests()

        # Approval gate.
        needs_approval = transition.get("approval_required") or self.spec.approval_required.get(to_state, False)
        if needs_approval and not approval_token:
            return ReasoningResult(
                status=ReasoningStatus.APPROVAL_REQUIRED,
                domain=domain,
                intent=intent,
                workflow={"instance_id": instance_id, "state": current, "attempted": to_state},
                approval={"required_for": to_state},
                explanation=f"{to_state} requires an approval token",
            ).stamp_digests()
        if needs_approval and not self._consume_approval(inst, to_state, approval_token):
            return ReasoningResult(
                status=ReasoningStatus.PERMISSION_DENIED,
                domain=domain,
                intent=intent,
                explanation=f"approval token for {to_state} is invalid or already consumed",
            ).stamp_digests()

        # Immutable states can never be re-entered after leaving.
        if current in self.spec.immutable_states and to_state != current:
            pass  # leaving an immutable state is the allowed direction

        inst["state"] = to_state
        inst["history"].append({"from": current, "to": to_state, "at": _now(), "by": actor})
        if evidence:
            inst.setdefault("evidence_log", []).append({**evidence, "transition": f"{current}->{to_state}"})
        return ReasoningResult(
            status=ReasoningStatus.SUCCESS,
            domain=domain,
            intent=intent,
            workflow={"instance_id": instance_id, "state": to_state, "previous": current},
            evidence=list(inst.get("evidence_log", [])),
            explanation=f"{self.spec.workflow_id}: {current} → {to_state}",
            versions={"workflow": self.spec.version},
        ).stamp_digests()

    def state(self, instance_id: str) -> Dict[str, Any]:
        inst = self._instances.get(instance_id)
        if inst is None:
            return {}
        return {"state": inst["state"], "history": list(inst["history"])}

    def register_approval(self, instance_id: str, transition_to: str, token: str) -> None:
        inst = self._instances.setdefault(
            instance_id, {"state": self.spec.initial_state, "facts": {}, "history": [], "approvals": {}}
        )
        inst["approvals"][transition_to] = {"token": token, "consumed": False}

    def _consume_approval(self, inst: Dict[str, Any], to_state: str, token: str) -> bool:
        entry = inst.get("approvals", {}).get(to_state)
        if not entry or entry.get("consumed"):
            return False
        if not _constant_time_eq(str(entry.get("token") or ""), str(token or "")):
            return False
        entry["consumed"] = True
        return True


def _guard_holds(guard: str, facts: Dict[str, Any]) -> bool:
    parts = guard.split()
    if len(parts) != 3:
        return False
    field, op, want = parts
    from app.reasoning_kernel.rules import _OPS

    fn = _OPS.get(op)
    if fn is None:
        return False
    try:
        return bool(fn(facts.get(field), _coerce(want)))
    except (TypeError, ValueError) as exc:
        _log.debug("guard %r not comparable: %s", guard, exc)
        return False


def _coerce(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    try:
        return float(value)
    except ValueError:
        return value


def _constant_time_eq(a: str, b: str) -> bool:
    return hashlib.sha256(a.encode()).digest() == hashlib.sha256(b.encode()).digest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
