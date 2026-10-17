"""Cerebrum Reasoning Kernel — the standard reasoning result envelope.

Every kernel engine returns (or contributes to) a ReasoningResult with the
exact status vocabulary the mission defines. The LLM may fill
``explanation``; it may never set a status, a trusted value, an approval,
or a workflow transition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class ReasoningStatus(str, Enum):
    SUCCESS = "success"
    DEPENDENCY_REQUIRED = "dependency_required"
    VALIDATION_ERROR = "validation_error"
    PERMISSION_DENIED = "permission_denied"
    APPROVAL_REQUIRED = "approval_required"
    UNSUPPORTED = "unsupported"
    CONFLICT_DETECTED = "conflict_detected"
    EXECUTION_ERROR = "execution_error"


@dataclass
class ReasoningResult:
    """The one result shape every engine produces."""

    status: ReasoningStatus = ReasoningStatus.SUCCESS
    domain: str = ""
    intent: str = ""
    scope: Dict[str, Any] = field(default_factory=dict)
    facts: List[Dict[str, Any]] = field(default_factory=list)
    assumptions: List[Dict[str, Any]] = field(default_factory=list)
    missing_inputs: List[str] = field(default_factory=list)
    rules_applied: List[Dict[str, Any]] = field(default_factory=list)
    formulas_applied: List[Dict[str, Any]] = field(default_factory=list)
    workflow: Dict[str, Any] = field(default_factory=dict)
    approval: Dict[str, Any] = field(default_factory=dict)
    recommended_actions: List[Dict[str, Any]] = field(default_factory=list)
    prohibited_actions: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    authority_sources: List[Dict[str, Any]] = field(default_factory=list)
    confidence: Dict[str, Any] = field(default_factory=dict)
    explanation: str = ""
    input_digest: str = ""
    output_digest: str = ""
    #: Engine + pack versions that produced this result.
    versions: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "status": self.status.value,
            "domain": self.domain,
            "intent": self.intent,
            "scope": dict(self.scope),
            "facts": [dict(f) for f in self.facts],
            "assumptions": [dict(a) for a in self.assumptions],
            "missing_inputs": list(self.missing_inputs),
            "rules_applied": [dict(r) for r in self.rules_applied],
            "formulas_applied": [dict(f) for f in self.formulas_applied],
            "workflow": dict(self.workflow),
            "approval": dict(self.approval),
            "recommended_actions": [dict(a) for a in self.recommended_actions],
            "prohibited_actions": [dict(a) for a in self.prohibited_actions],
            "evidence": [dict(e) for e in self.evidence],
            "authority_sources": [dict(a) for a in self.authority_sources],
            "confidence": dict(self.confidence),
            "explanation": self.explanation,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "versions": dict(self.versions),
        }
        out["generated_at"] = datetime.now(timezone.utc).isoformat()
        return out

    def stamp_digests(self) -> "ReasoningResult":
        """Digest the structural output (never the model's explanation).

        Explanation text is excluded so a model rephrase cannot move the
        digest; only engine outputs are trusted content.
        """
        import hashlib
        import json

        structural = self.to_dict()
        structural.pop("generated_at", None)
        structural.pop("explanation", None)
        payload = json.dumps(structural, sort_keys=True, default=str)
        self.output_digest = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()
        return self
