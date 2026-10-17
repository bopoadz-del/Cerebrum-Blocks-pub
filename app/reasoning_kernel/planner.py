"""Domain pack version manager + reasoning planner (kernel components).

- DomainPackVersionManager: pins a pack version; a product running a
  different version than the one recorded in provenance is refused by
  name. Versions are never edited in place.
- ReasoningPlanner + ActionPlanValidator: plan the reasoning steps for
  an intent (which rules/formulas/workflow apply) and validate an action
  plan before execution. The plan names what WILL run; execution is a
  separate, gated step.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.reasoning_kernel import ReasoningResult, ReasoningStatus
from app.reasoning_kernel.schemas import DomainPack

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class DomainPackVersionManager:
    def __init__(self, pack: DomainPack) -> None:
        self.pack = pack
        self._pin: Optional[str] = None

    def pin(self, version: str) -> None:
        if not _VERSION_RE.match(version):
            raise ValueError(f"invalid pack version: {version!r}")
        self._pin = version

    def verify(self, running_version: str, *, domain: str = "", intent: str = "") -> ReasoningResult:
        if self._pin is None:
            return ReasoningResult(
                status=ReasoningStatus.DEPENDENCY_REQUIRED,
                domain=domain,
                intent=intent,
                missing_inputs=["pack_pin"],
                explanation="no pack version pinned — refusing to run unpinned",
            ).stamp_digests()
        if self._pin != running_version:
            return ReasoningResult(
                status=ReasoningStatus.CONFLICT_DETECTED,
                domain=domain,
                intent=intent,
                explanation=f"pack pinned at {self._pin}; running {running_version} — version mismatch refused",
                versions={"pinned": self._pin, "running": running_version},
            ).stamp_digests()
        return ReasoningResult(
            status=ReasoningStatus.SUCCESS,
            domain=domain,
            intent=intent,
            versions={"pack": self._pin},
            explanation=f"pack version {self._pin} verified",
        ).stamp_digests()


class ReasoningPlanner:
    """Build a reasoning plan for an intent from the pack's artifacts.

    The plan names the rules/formulas/workflow/approvals that WOULD apply.
    It never executes them; execution is the gated runner's job.
    """

    def __init__(self, pack: DomainPack) -> None:
        self.pack = pack

    def plan(self, intent: str, facts: Dict[str, Any], *, domain: str = "") -> ReasoningResult:
        applicable_rules = [
            {"rule_id": r.rule_id, "version": r.version}
            for r in self.pack.rules
            if _rule_might_apply(r, facts)
        ]
        applicable_formulas = [
            {"formula_id": f.formula_id, "version": f.version}
            for f in self.pack.formulas
        ]
        workflow = (
            {"workflow_id": w.workflow_id, "initial_state": w.initial_state}
            for w in self.pack.workflows
        )
        workflow_list = list(workflow)[:1]
        return ReasoningResult(
            status=ReasoningStatus.SUCCESS,
            domain=domain or self.pack.manifest.domain_id,
            intent=intent,
            facts=[{"intent": intent, "fact_keys": sorted(facts.keys())}],
            rules_applied=[],  # planning only — nothing applied yet
            recommended_actions=[
                {"plan": "rules", "items": applicable_rules},
                {"plan": "formulas", "items": applicable_formulas},
                {"plan": "workflow", "items": workflow_list},
            ],
            explanation=(
                f"plan for {intent!r}: {len(applicable_rules)} rule(s), "
                f"{len(applicable_formulas)} formula(s) available"
            ),
            versions={"pack": self.pack.manifest.version},
        ).stamp_digests()


class ActionPlanValidator:
    """Validate an action plan before execution: every action must be a
    declared pack action; prohibited/unsupported actions are refused by
    name; trusted fields cannot be overridden by plan payloads."""

    TRUSTED_FIELDS = {"status", "approval", "workflow_state", "authority", "certification"}

    def __init__(self, pack: DomainPack) -> None:
        self.pack = pack

    def validate(self, actions: List[Dict[str, Any]], *, domain: str = "", intent: str = "") -> ReasoningResult:
        declared = set(self.pack.actions.keys())
        errors: List[str] = []
        for action in actions:
            name = str(action.get("action") or "")
            if not name:
                errors.append("action without a name")
                continue
            if name not in declared:
                errors.append(f"{name!r} is not a declared pack action")
            for field in self.TRUSTED_FIELDS:
                if field in action:
                    errors.append(
                        f"{name}: plan payload sets trusted field {field!r} — the model cannot override it"
                    )
        if errors:
            return ReasoningResult(
                status=ReasoningStatus.VALIDATION_ERROR,
                domain=domain,
                intent=intent,
                prohibited_actions=[{"reason": e} for e in errors],
                explanation="action plan refused: " + "; ".join(errors[:5]),
            ).stamp_digests()
        return ReasoningResult(
            status=ReasoningStatus.SUCCESS,
            domain=domain,
            intent=intent,
            recommended_actions=[dict(a) for a in actions],
            explanation=f"action plan valid ({len(actions)} action(s))",
        ).stamp_digests()


def _rule_might_apply(rule, facts: Dict[str, Any]) -> bool:
    conditions = rule.conditions or []
    if not conditions:
        return False
    fields = {c.get("field") for c in conditions if isinstance(c, dict)}
    return bool(fields & set(facts.keys()))
