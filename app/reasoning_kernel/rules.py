"""Rule engine + decision table engine (kernel components).

Rules match facts deterministically; conflicting authoritative rules
produce ``conflict_detected`` — never a silent pick. A rule's refusal
behavior is honored by name ("refuse" returns the rule decision with a
refusal status; "warn" records the rule and continues). The LLM cannot
insert, reorder, or override a rule at evaluation time.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional

from app.reasoning_kernel import ReasoningResult, ReasoningStatus
from app.reasoning_kernel.schemas import DecisionTableSpec, RuleSpec

_log = logging.getLogger(__name__)

_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
}


class RuleEngine:
    def __init__(self, rules: Optional[List[RuleSpec]] = None) -> None:
        self._rules: Dict[str, RuleSpec] = {}
        for rule in rules or []:
            self.add(rule)

    def add(self, rule: RuleSpec) -> None:
        self._rules[rule.rule_id] = rule

    def rules(self) -> List[RuleSpec]:
        return sorted(self._rules.values(), key=lambda r: (-r.precedence, r.rule_id))

    def evaluate(self, facts: Dict[str, Any], *, domain: str = "", intent: str = "") -> ReasoningResult:
        today = date.today().isoformat()
        matched: List[RuleSpec] = []
        for rule in self.rules():
            if rule.effective_date and rule.effective_date.isoformat() > today:
                continue
            if _matches(rule.conditions, facts, exceptions=rule.exceptions):
                matched.append(rule)

        if not matched:
            return ReasoningResult(
                status=ReasoningStatus.SUCCESS,
                domain=domain,
                intent=intent,
                explanation="no rules matched",
            ).stamp_digests()

        # Conflict detection: same precedence, different decisions, no
        # declared conflict resolution -> refuse with conflict_detected.
        top = max(r.precedence for r in matched)
        winners = [r for r in matched if r.precedence == top]
        decisions = {_decision_key(r.decision) for r in winners}
        if len(winners) > 1 and len(decisions) > 1:
            return ReasoningResult(
                status=ReasoningStatus.CONFLICT_DETECTED,
                domain=domain,
                intent=intent,
                rules_applied=[_rule_record(r, facts) for r in winners],
                explanation=(
                    "conflicting rules matched at the same precedence: "
                    + ", ".join(r.rule_id for r in winners)
                ),
            ).stamp_digests()

        result = ReasoningResult(domain=domain, intent=intent)
        for rule in sorted(winners, key=lambda r: r.rule_id):
            rec = _rule_record(rule, facts)
            result.rules_applied.append(rec)
            if rule.refusal_behavior == "refuse":
                result.status = ReasoningStatus.VALIDATION_ERROR
                result.prohibited_actions.append({"rule_id": rule.rule_id, "decision": rule.decision})
        if result.status is not ReasoningStatus.VALIDATION_ERROR:
            result.status = ReasoningStatus.SUCCESS
            for rule in winners:
                if rule.decision.get("outcome"):
                    result.recommended_actions.append({"rule_id": rule.rule_id, "decision": rule.decision})
        result.explanation = "; ".join(
            f"{r.rule_id}: {r.decision.get('message') or r.decision.get('outcome') or 'matched'}"
            for r in winners
        )
        return result.stamp_digests()


class DecisionTableEngine:
    """Exact-match rows over named inputs; no fuzzy matching."""

    def __init__(self, spec: DecisionTableSpec) -> None:
        self.spec = spec

    def evaluate(self, inputs: Dict[str, Any], *, domain: str = "", intent: str = "") -> ReasoningResult:
        for row in self.spec.rows:
            conditions = row.get("when") or row.get("conditions") or {}
            if not isinstance(conditions, dict):
                continue
            if all(_op_matches(inputs.get(k), v) for k, v in conditions.items()):
                outcome = row.get("then") or row.get("outcome") or row.get("decision") or {}
                return ReasoningResult(
                    status=ReasoningStatus.SUCCESS,
                    domain=domain,
                    intent=intent,
                    facts=[{"table_id": self.spec.table_id, "row": row}],
                    recommended_actions=[{"table_id": self.spec.table_id, "outcome": outcome}],
                    authority_sources=[{"table_id": self.spec.table_id, "authority": self.spec.authority_source}],
                    explanation=f"{self.spec.table_id}: {outcome}",
                    versions={"table": self.spec.version},
                ).stamp_digests()
        return ReasoningResult(
            status=ReasoningStatus.SUCCESS,
            domain=domain,
            intent=intent,
            recommended_actions=[{"table_id": self.spec.table_id, "outcome": self.spec.default_outcome}],
            explanation=f"{self.spec.table_id}: no row matched — default outcome",
        ).stamp_digests()


def _matches(conditions: List[Dict[str, Any]], facts: Dict[str, Any], *, exceptions: List[Dict[str, Any]]) -> bool:
    if not conditions:
        return True
    if not all(_op_matches(facts.get(c["field"]), c) for c in conditions):
        return False
    for exc in exceptions:
        if not exc:
            continue
        exc_cond = exc.get("when") or exc.get("conditions")
        if isinstance(exc_cond, dict) and all(_op_matches(facts.get(k), v) for k, v in exc_cond.items()):
            return False
    return True


def _op_matches(actual: Any, cond: Any) -> bool:
    """Match a single condition. Dict conditions carry {op, value}; bare
    values mean equality."""
    if not isinstance(cond, dict):
        return actual == cond
    op = cond.get("op", "eq")
    value = cond.get("value")
    fn = _OPS.get(op)
    if fn is None:
        return False
    try:
        return bool(fn(actual, value))
    except (TypeError, ValueError) as exc:
        _log.debug("condition mismatch %r %r: %s", actual, value, exc)
        return False


def _decision_key(decision: Dict[str, Any]) -> str:
    return repr(sorted(decision.items()))


def _rule_record(rule: RuleSpec, facts: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "rule_id": rule.rule_id,
        "version": rule.version,
        "decision": rule.decision,
        "severity": rule.severity,
        "precedence": rule.precedence,
        "authority_source": rule.authority_source,
        "evidence_requirements": rule.evidence_requirements,
    }
