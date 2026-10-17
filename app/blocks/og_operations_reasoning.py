"""Oil & gas operations reasoning gate — store-facing wrapper.

The reasoning layer itself lives in ``app.blocks.og_operations.reasoning``
(the gate, the two-source live-state model and the operating-basis
manifest). This module is the census-facing entrypoint: the block id is
``og_operations_reasoning``, the class carries identity metadata, and every
statement is routed through ``gate_answer`` — there is no bypass.

Provenance: structure only. The domain encoding sheet for Oil & Gas
Operations defines the invariants and the guard; NO INTERVIEW HAS RUN, so
every manifest value is null (``app/blocks/og_operations/KNOWN_GAPS.md``).
This block refuses; it does not supply figures it does not have. The verdict
pattern follows ``app.blocks.offshore_marine_reasoning`` and the aviation
grounding gate.
"""
from __future__ import annotations

from typing import Any, Dict

from app.blocks.og_operations.reasoning import (
    LiveState,
    OperatingBasis,
    gate_answer,
)
from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "og_operations_reasoning",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


class OgOperationsReasoningBlock(UniversalBlock):
    name = "og_operations_reasoning"
    version = "1.0.0"
    description = (
        "Deterministic oil & gas operations reasoning gate. Every statement "
        "passes INV-1 (pressure figures name which pressure — design|mawp|"
        "operating — gauge or absolute, and a location), INV-2 (envelope "
        "figures carry envelope_tier normal|alarm|trip|SOL|design), INV-3 "
        "(protective-function / SCE answers carry BOTH an override_register_ref "
        "and an isolation_register_ref), INV-4 (flow is std|normal|actual, "
        "concentration is %LEL|%vol|ppm, exposure is TWA|STEL|ceiling), INV-5 "
        "(figures cited from a P&ID or procedure carry a revision and an MOC "
        "state), the never-allowed derivations, the monitoring + override/"
        "isolation/permit-log live-state gate, REJECT_AS_PROOF and the "
        "sister-asset trap. Keep-running, containment, trip-bypass, "
        "inspection-extension and fitness-for-service questions are refused "
        "BEFORE retrieval. Blocked and refused statements fail loud; nothing "
        "is invented."
    )
    layer = 3
    tags = ["oil_gas", "operations", "process_safety", "grounding", "gate", "sce"]
    requires: list = []

    async def process(self, input_data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            query = str(input_data.get("query") or params.get("query") or "").strip()
            answer = str(input_data.get("answer") or params.get("answer") or "").strip()
            if not query or not answer:
                return _envelope("refused", error="query and answer are required")

            raw_state = input_data.get("live_state")
            if raw_state is None:
                state = None
            elif isinstance(raw_state, LiveState):
                state = raw_state
            elif isinstance(raw_state, dict):
                state = LiveState(
                    monitoring=raw_state.get("monitoring"),
                    manual_log=raw_state.get("manual_log"),
                    fetched_at=raw_state.get("fetched_at"),
                )
            else:
                return _envelope(
                    "refused",
                    error="live_state must be {monitoring, manual_log, fetched_at}",
                )

            evidence = input_data.get("evidence") or []
            if isinstance(evidence, str):
                evidence = [evidence]

            verdict = gate_answer(
                query,
                answer,
                live_state=state,
                pressure_kind=input_data.get("pressure_kind"),
                gauge_or_absolute=input_data.get("gauge_or_absolute"),
                location=input_data.get("location"),
                envelope_tier=input_data.get("envelope_tier"),
                override_register_ref=input_data.get("override_register_ref"),
                isolation_register_ref=input_data.get("isolation_register_ref"),
                citation_rev=input_data.get("citation_rev"),
                citation_moc_state=input_data.get("citation_moc_state"),
                evidence=list(evidence),
                moc_approved_since_pid=bool(input_data.get("moc_approved_since_pid")),
                inspection_overdue=bool(input_data.get("inspection_overdue")),
                psv_interval_elapsed=bool(input_data.get("psv_interval_elapsed")),
                sif_proof_test_overdue=bool(input_data.get("sif_proof_test_overdue")),
                process_changed_since_hazop=bool(input_data.get("process_changed_since_hazop")),
                procedure_revision_changed=bool(input_data.get("procedure_revision_changed")),
                gas_detector_calibration_overdue=bool(
                    input_data.get("gas_detector_calibration_overdue")
                ),
            )
            basis = OperatingBasis()
            verdict["interview_status"] = basis.interview_status
            verdict["unfilled_figures"] = basis.unfilled()
            return _envelope("success", result=verdict)
        except Exception as exc:  # noqa: BLE001 — a gate that dies silently is worse
            return _envelope("error", error=f"{type(exc).__name__}: {exc}")
