"""Domain pack loader + validator (kernel components).

A pack is validated against its schema AND its internal consistency
(formula/rule/workflow/approval references, duplicate ids, conflicting
formula registrations) before it loads. A validation failure is a load
refusal with named reasons — never a partially-loaded pack.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from app.reasoning_kernel.schemas import DomainPack


class PackLoadError(Exception):
    """A pack failed to load; ``reasons`` names every defect."""

    def __init__(self, reasons: List[str]):
        self.reasons = reasons
        super().__init__("; ".join(reasons))


class DomainPackValidator:
    def validate(self, raw: Dict[str, Any]) -> DomainPack:
        try:
            pack = DomainPack.model_validate(raw)
        except ValidationError as exc:
            raise PackLoadError([f"schema: {e['loc']}: {e['msg']}" for e in exc.errors()]) from exc
        reasons = self._consistency_errors(pack)
        if reasons:
            raise PackLoadError(reasons)
        return pack

    def _consistency_errors(self, pack: DomainPack) -> List[str]:
        reasons: List[str] = []
        ids = [f.formula_id for f in pack.formulas]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            reasons.append("duplicate formula ids: " + ", ".join(dupes))
        for formula in pack.formulas:
            if formula.currency and not formula.currency.isupper():
                reasons.append(f"{formula.formula_id}: currency must be an ISO code")
        for rule in pack.rules:
            if not rule.conditions:
                reasons.append(f"{rule.rule_id}: a rule with no conditions matches everything")
        for wf in pack.workflows:
            if wf.initial_state and wf.initial_state not in wf.states:
                reasons.append(f"{wf.workflow_id}: initial_state not in states")
            declared = {(t.get("from"), t.get("to")) for t in wf.transitions}
            for t in wf.transitions:
                if t.get("from") not in wf.states or t.get("to") not in wf.states:
                    reasons.append(f"{wf.workflow_id}: transition references unknown state")
        for ap in pack.approvals:
            if ap.self_approval not in {"prohibited", "allowed_with_evidence"}:
                reasons.append(f"{ap.action}: self_approval must be prohibited or allowed_with_evidence")
        return reasons


class DomainPackLoader:
    """Load packs by path (single JSON document)."""

    def __init__(self, validator: Optional[DomainPackValidator] = None) -> None:
        self.validator = validator or DomainPackValidator()

    def load(self, raw: Dict[str, Any]) -> DomainPack:
        return self.validator.validate(raw)

    def load_path(self, path: str) -> DomainPack:
        import json
        from pathlib import Path

        p = Path(path)
        if not p.is_file():
            raise PackLoadError([f"pack file not found: {path}"])
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PackLoadError([f"unreadable pack: {exc}"]) from exc
        return self.load(raw)
