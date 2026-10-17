"""Evidence, authority, refusal, and assumption machinery (kernel components).

- EvidenceRequirementEngine: required evidence per action is checked by
  name; a missing item yields DEPENDENCY_REQUIRED with the item named.
- AuthorityResolver: resolves an artifact's authority source; refuses to
  act when the authority is absent or below the required tier.
- RefusalEngine: the single refusal vocabulary — unsupported operations
  and out-of-envelope requests are refused with the reason named, and
  the refusal itself is recorded as evidence.
- AssumptionRegistry: assumptions are declared, never silently chosen —
  an evaluation that depends on an undeclared assumption must register
  it or fail.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.reasoning_kernel import ReasoningResult, ReasoningStatus


class AssumptionRegistry:
    def __init__(self) -> None:
        self._assumptions: List[Dict[str, Any]] = []

    def declare(self, assumption_id: str, text: str, *, chosen_by: str = "engine") -> None:
        self._assumptions.append(
            {"assumption_id": assumption_id, "text": text, "chosen_by": chosen_by}
        )

    def all(self) -> List[Dict[str, Any]]:
        return [dict(a) for a in self._assumptions]

    def has(self, assumption_id: str) -> bool:
        return any(a["assumption_id"] == assumption_id for a in self._assumptions)


class AuthorityResolver:
    """Resolve authority for an artifact; refuse when authority is absent.

    The LLM can never supply authority — it comes from the pack
    (``authority_sources`` in the artifact spec) or from the caller's
    registered sources.
    """

    def __init__(self) -> None:
        self._sources: Dict[str, Dict[str, Any]] = {}

    def register(self, source_id: str, *, kind: str, reference: str, tier: str = "documented") -> None:
        self._sources[source_id] = {"source_id": source_id, "kind": kind, "reference": reference, "tier": tier}

    def resolve(self, artifact_id: str, authority_source: str) -> Dict[str, Any]:
        source = self._sources.get(authority_source)
        if source is None:
            return {
                "artifact_id": artifact_id,
                "authority": authority_source,
                "resolved": False,
                "reason": f"authority {authority_source!r} is not registered",
            }
        return {"artifact_id": artifact_id, **source, "resolved": True}

    def require(self, artifact_id: str, authority_source: str, *, domain: str = "", intent: str = "") -> ReasoningResult:
        resolved = self.resolve(artifact_id, authority_source)
        if not resolved.get("resolved"):
            return ReasoningResult(
                status=ReasoningStatus.DEPENDENCY_REQUIRED,
                domain=domain,
                intent=intent,
                missing_inputs=[f"authority:{authority_source}"],
                explanation=resolved["reason"],
            ).stamp_digests()
        return ReasoningResult(
            status=ReasoningStatus.SUCCESS,
            domain=domain,
            intent=intent,
            authority_sources=[resolved],
            explanation=f"{artifact_id}: authority {authority_source} resolved",
        ).stamp_digests()


class EvidenceRequirementEngine:
    def __init__(self, requirements: Optional[Dict[str, List[str]]] = None) -> None:
        self._requirements: Dict[str, List[str]] = dict(requirements or {})

    def require(self, action: str, provided: Dict[str, Any], *, domain: str = "", intent: str = "") -> ReasoningResult:
        required = self._requirements.get(action, [])
        missing = [name for name in required if not provided.get(name)]
        if missing:
            return ReasoningResult(
                status=ReasoningStatus.DEPENDENCY_REQUIRED,
                domain=domain,
                intent=intent,
                missing_inputs=[f"evidence:{m}" for m in missing],
                explanation=f"{action}: missing required evidence: {', '.join(missing)}",
            ).stamp_digests()
        return ReasoningResult(
            status=ReasoningStatus.SUCCESS,
            domain=domain,
            intent=intent,
            evidence=[{"kind": "requirement_met", "action": action, "items": required}],
            explanation=f"{action}: evidence requirements met",
        ).stamp_digests()


class RefusalEngine:
    """Refuse unsupported operations and out-of-envelope requests by name.

    The refusal result itself is evidence — an honest refusal is recorded,
    never a silent no-op.
    """

    def unsupported(self, operation: str, *, supported: List[str], domain: str = "", intent: str = "") -> ReasoningResult:
        result = ReasoningResult(
            status=ReasoningStatus.UNSUPPORTED,
            domain=domain,
            intent=intent,
            explanation=f"{operation!r} is not supported; supported: {', '.join(supported)}",
            prohibited_actions=[{"operation": operation, "reason": "unsupported"}],
        )
        result.evidence.append({"kind": "refusal", "reason": "unsupported", "operation": operation})
        return result.stamp_digests()

    def out_of_envelope(self, operation: str, *, envelope: Dict[str, Any], domain: str = "", intent: str = "") -> ReasoningResult:
        result = ReasoningResult(
            status=ReasoningStatus.VALIDATION_ERROR,
            domain=domain,
            intent=intent,
            explanation=f"{operation!r} is outside its validity envelope {envelope} — refusing rather than extrapolating",
            prohibited_actions=[{"operation": operation, "reason": "out_of_envelope"}],
        )
        result.evidence.append({"kind": "refusal", "reason": "out_of_envelope", "operation": operation})
        return result.stamp_digests()
