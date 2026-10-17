"""Ontology registry + permission resolver (kernel components).

- OntologyRegistry: the pack's domain vocabulary — canonical terms,
  aliases, units, and entity kinds. Resolution refuses unknown terms
  by name; the LLM cannot mint a term on the fly.
- PermissionResolver: the trust-spine chain user → role → permission →
  action, deny-by-default. An action with no declared permission is
  refused, not assumed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from app.reasoning_kernel import ReasoningResult, ReasoningStatus


class OntologyRegistry:
    def __init__(self, ontology: Optional[Dict[str, Any]] = None) -> None:
        self._terms: Dict[str, Dict[str, Any]] = {}
        self._aliases: Dict[str, str] = {}
        raw = ontology or {}
        for term_id, spec in raw.get("terms", {}).items():
            self._terms[str(term_id)] = dict(spec or {})
            for alias in spec.get("aliases") or []:
                self._aliases[str(alias).lower()] = str(term_id)

    def canonicalize(self, term: str) -> str:
        key = str(term).lower()
        if key in self._aliases:
            return self._aliases[key]
        if key in self._terms:
            return key
        return ""

    def resolve(self, term: str, *, domain: str = "", intent: str = "") -> ReasoningResult:
        canonical = self.canonicalize(term)
        if not canonical:
            return ReasoningResult(
                status=ReasoningStatus.UNSUPPORTED,
                domain=domain,
                intent=intent,
                missing_inputs=[f"term:{term}"],
                explanation=f"term {term!r} is not in the ontology",
            ).stamp_digests()
        return ReasoningResult(
            status=ReasoningStatus.SUCCESS,
            domain=domain,
            intent=intent,
            facts=[{"term": term, "canonical": canonical, **self._terms.get(canonical, {})}],
            explanation=f"{term!r} → {canonical}",
        ).stamp_digests()

    def terms(self) -> List[str]:
        return sorted(self._terms)


class PermissionResolver:
    """Deny-by-default permission chain.

    ``permissions`` maps role → set of permitted actions (or "*").
    ``action_requirements`` maps action → required permission id; an
    action with no declared requirement is refused (never assumed safe).
    """

    def __init__(
        self,
        permissions: Optional[Dict[str, List[str]]] = None,
        action_requirements: Optional[Dict[str, str]] = None,
    ) -> None:
        self._permissions: Dict[str, Set[str]] = {
            role: set(actions) for role, actions in (permissions or {}).items()
        }
        self._action_requirements: Dict[str, str] = dict(action_requirements or {})

    def check(
        self,
        role: str,
        action: str,
        *,
        scope: Optional[Dict[str, Any]] = None,
        domain: str = "",
        intent: str = "",
    ) -> ReasoningResult:
        required = self._action_requirements.get(action)
        if required is None:
            return ReasoningResult(
                status=ReasoningStatus.PERMISSION_DENIED,
                domain=domain,
                intent=intent,
                scope=dict(scope or {}),
                explanation=f"action {action!r} has no declared permission requirement — denied by default",
            ).stamp_digests()
        granted = self._permissions.get(role, set())
        if required not in granted and "*" not in granted:
            return ReasoningResult(
                status=ReasoningStatus.PERMISSION_DENIED,
                domain=domain,
                intent=intent,
                scope=dict(scope or {}),
                explanation=f"role {role!r} lacks permission {required!r} for {action!r}",
            ).stamp_digests()
        return ReasoningResult(
            status=ReasoningStatus.SUCCESS,
            domain=domain,
            intent=intent,
            scope=dict(scope or {}),
            facts=[{"role": role, "action": action, "permission": required}],
            explanation=f"{role}: {action} permitted via {required}",
        ).stamp_digests()
