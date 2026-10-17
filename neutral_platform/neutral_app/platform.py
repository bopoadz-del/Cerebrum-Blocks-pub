"""Kernel wiring for the neutral proof platform.

Loads the equipment_maintenance pack and wires the REAL kernel engines:
DeterministicFormulaExecutor (production mode), RuleEngine,
DecisionTableEngine, WorkflowEngine, ApprovalMatrixEngine and
ExplanationComposer. The API layer only ever proposes — every gate,
calculation, refusal and transition is decided by the kernel.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.reasoning_kernel import ReasoningResult, ReasoningStatus
from app.reasoning_kernel.approvals import ApprovalMatrixEngine, payload_digest
from app.reasoning_kernel.formulas import (
    DeterministicFormulaExecutor,
    FormulaRegistry,
)
from app.reasoning_kernel.loader import DomainPackLoader
from app.reasoning_kernel.oracles import ExplanationComposer
from app.reasoning_kernel.rules import DecisionTableEngine, RuleEngine
from app.reasoning_kernel.workflow import WorkflowEngine

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_PATH = REPO_ROOT / "domain_packs" / "equipment_maintenance" / "pack.json"

BAND_THRESHOLD = 3  # likelihood/consequence >= 3 counts as the high band


# -- formula implementations (deterministic, Decimal) -----------------------


def _risk_score(inputs: Dict[str, Decimal]) -> Decimal:
    return inputs["likelihood"] * inputs["consequence"]


def _service_overdue(inputs: Dict[str, Decimal]) -> bool:
    return inputs["hours_since_service"] >= inputs["service_interval_hours"]


class NeutralPlatform:
    """One wired kernel instance (engines + pack)."""

    def __init__(self) -> None:
        self.pack = DomainPackLoader().load_path(str(PACK_PATH))
        registry = FormulaRegistry()
        registry.register(self._formula_spec("equipment_maintenance.risk_score"), _risk_score)
        registry.register(self._formula_spec("equipment_maintenance.service_overdue"), _service_overdue)
        self.formulas = DeterministicFormulaExecutor(registry, production=True)
        self.rules = RuleEngine(self.pack.rules)
        self.matrix = DecisionTableEngine(self.pack.decision_tables[0])
        self.workflow = WorkflowEngine(self.pack.workflows[0])
        self.approvals = ApprovalMatrixEngine(self.pack.approvals)
        self.composer = ExplanationComposer()

    def _formula_spec(self, formula_id: str):
        for spec in self.pack.formulas:
            if spec.formula_id == formula_id:
                return spec
        raise KeyError(formula_id)

    # -- inspection --------------------------------------------------------

    def run_inspection(self, payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[ReasoningResult]]:
        """Run the inspection through the kernel. Returns (inspection, results).

        inspection is None when a refusal rule fires — the caller must
        refuse the request with the results' explanation.
        """
        results: List[ReasoningResult] = []
        facts = dict(payload)

        risk = self.formulas.execute(
            "equipment_maintenance.risk_score",
            {"likelihood": payload["likelihood"], "consequence": payload["consequence"]},
            domain="equipment_maintenance",
            intent="equipment_inspection",
        )
        results.append(risk)
        facts["risk_score"] = int(risk.formulas_applied[0]["output"]) if risk.formulas_applied else None

        overdue = self.formulas.execute(
            "equipment_maintenance.service_overdue",
            {
                "hours_since_service": payload["hours_since_service"],
                "service_interval_hours": payload["service_interval_hours"],
            },
            domain="equipment_maintenance",
            intent="equipment_inspection",
        )
        results.append(overdue)
        facts["service_overdue"] = overdue.formulas_applied[0]["output"] == "True" if overdue.formulas_applied else None

        rule_result = self.rules.evaluate(facts, domain="equipment_maintenance", intent="equipment_inspection")
        results.append(rule_result)
        if rule_result.status is ReasoningStatus.VALIDATION_ERROR and rule_result.prohibited_actions:
            return None, results

        likelihood_band = "high" if int(payload["likelihood"]) >= BAND_THRESHOLD else "low"
        consequence_band = "high" if int(payload["consequence"]) >= BAND_THRESHOLD else "low"
        table = self.matrix.evaluate(
            {"likelihood_band": likelihood_band, "consequence_band": consequence_band},
            domain="equipment_maintenance",
            intent="equipment_inspection",
        )
        results.append(table)

        actions = [rec for rec in rule_result.recommended_actions]
        if table.recommended_actions:
            actions.append(table.recommended_actions[0])
        band = table.recommended_actions[0]["outcome"]["band"] if table.recommended_actions else "low"

        lines = [self.composer.compose(r) for r in results]
        explanation = "\n".join(line for line in lines if line)
        inspection = {
            **payload,
            "risk_score": facts["risk_score"],
            "risk_band": band,
            "actions": actions,
            "explanation": explanation,
        }
        return inspection, results

    # -- work orders --------------------------------------------------------

    def create_work_order(
        self, work_order_id: str, inspection: Dict[str, Any]
    ) -> ReasoningResult:
        return self.workflow.create(
            work_order_id,
            facts={
                "risk_score": inspection["risk_score"],
                "risk_band": inspection["risk_band"],
                "priority": (
                    "immediate"
                    if inspection["risk_band"] == "critical"
                    else "routine"
                ),
            },
        )

    def transition(
        self,
        work_order_id: str,
        to_state: str,
        *,
        actor: str,
        evidence: Optional[Dict[str, Any]] = None,
        approval_token: Optional[str] = None,
        requester_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> ReasoningResult:
        if to_state == "closed" and approval_token:
            # The approval gate: validate the token against the approval
            # policy (roles, SoD, payload binding, expiry, replay) BEFORE
            # the workflow consumes it.
            check = self.approvals.check(
                "close_work_order",
                {"role": actor, "id": requester_id or ""},
                payload or {},
                value=None,
                approvals=[{"token": approval_token, "requester_id": requester_id or ""}],
                domain="equipment_maintenance",
                intent="close_work_order",
            )
            if check.status is not ReasoningStatus.SUCCESS:
                return check
            self.workflow.register_approval(work_order_id, "closed", approval_token)
        return self.workflow.transition(
            work_order_id,
            to_state,
            actor=actor,
            evidence=evidence,
            approval_token=approval_token,
            domain="equipment_maintenance",
            intent="work_order_transition",
        )

    def approval_requirement(self, payload: Dict[str, Any], requester: Dict[str, Any]) -> ReasoningResult:
        return self.approvals.check(
            "close_work_order",
            requester,
            payload,
            value=None,
            approvals=[],
            domain="equipment_maintenance",
            intent="close_work_order",
        )

    def issue_approval(
        self,
        *,
        approver: Dict[str, Any],
        payload: Dict[str, Any],
        ttl_seconds: Optional[int] = None,
    ) -> str:
        return self.approvals.issue(
            "close_work_order",
            approver=approver,
            payload=payload,
            ttl_seconds=ttl_seconds,
        )

    def state(self, work_order_id: str) -> Dict[str, Any]:
        return self.workflow.state(work_order_id)

    def audit_log(self) -> List[Dict[str, Any]]:
        return self.approvals.audit_log()


_platform: Optional[NeutralPlatform] = None


def get_platform() -> NeutralPlatform:
    global _platform
    if _platform is None:
        _platform = NeutralPlatform()
    return _platform


def reset_platform() -> None:
    global _platform
    _platform = None


def close_payload(work_order_id: str) -> Dict[str, Any]:
    return {"work_order_id": work_order_id, "target_state": "closed"}
