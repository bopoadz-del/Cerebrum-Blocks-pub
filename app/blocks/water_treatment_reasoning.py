"""Water treatment plant operations reasoning gate — store-facing wrapper.

The reasoning layer itself lives in ``app.blocks.water_treatment.reasoning``
(the gate, the two-source live-state model and the treatment-basis
manifest). This module is the store-facing entrypoint: the block id is
``water_treatment_reasoning``, the class carries identity metadata, and every
statement is routed through ``gate_answer`` — there is no bypass.

Provenance: structure only. The domain encoding sheet for Water Treatment
Plant Operations defines the invariants and the guard; NO INTERVIEW HAS RUN,
so every manifest value is null (``app/blocks/water_treatment/KNOWN_GAPS.md``).
This block refuses; it does not supply figures it does not have. The verdict
pattern follows ``app.blocks.offshore_marine_reasoning`` and the aviation
grounding gate.
"""
from __future__ import annotations

from typing import Any, Dict

from app.blocks.water_treatment.reasoning import (
    PlantState,
    TreatmentBasis,
    gate_answer,
)
from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "water_treatment_reasoning",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


class WaterTreatmentReasoningBlock(UniversalBlock):
    name = "water_treatment_reasoning"
    version = "1.0.0"
    description = (
        "Deterministic water treatment plant operations reasoning gate. "
        "Every statement passes INV-1 (CT value carries temperature, pH, "
        "disinfectant, organism and log target), INV-2 (contact time carries "
        "its basis theoretical|T10|tracer, the flow it applies at, and the "
        "tank level assumed), INV-3 (dose carries its basis as_product|"
        "as_active and the delivered, measured strength), INV-4 (a limit "
        "carries averaging basis, monitoring frequency and the named "
        "regulation), INV-5 (two sources conflicting on a limit are refused "
        "and both are reported — never a winner picked), the never-allowed "
        "derivations, the SCADA/analyser + chemical-delivery-log two-source "
        "live-state gate, REJECT_AS_PROOF and the similar-plant trap. "
        "Go/no-go safety questions are refused BEFORE retrieval. Blocked "
        "and refused statements fail loud; nothing is invented."
    )
    layer = 3
    tags = ["water", "treatment", "plant", "disinfection", "gate", "ct"]
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
            elif isinstance(raw_state, PlantState):
                state = raw_state
            elif isinstance(raw_state, dict):
                if "scada" not in raw_state or "delivery_log" not in raw_state:
                    return _envelope(
                        "refused",
                        error="live_state must be {scada, delivery_log, fetched_at}",
                    )
                state = PlantState(
                    scada=raw_state.get("scada"),
                    delivery_log=raw_state.get("delivery_log"),
                    fetched_at=raw_state.get("fetched_at"),
                )
            else:
                return _envelope(
                    "refused",
                    error="live_state must be {scada, delivery_log, fetched_at}",
                )

            evidence = input_data.get("evidence") or []
            if isinstance(evidence, str):
                evidence = [evidence]

            verdict = gate_answer(
                query,
                answer,
                live_state=state,
                ct_temperature_c=input_data.get("ct_temperature_c"),
                ct_ph=input_data.get("ct_ph"),
                disinfectant=input_data.get("disinfectant"),
                organism=input_data.get("organism"),
                log_target=input_data.get("log_target"),
                contact_time_basis=input_data.get("contact_time_basis"),
                flow=input_data.get("flow"),
                tank_level_assumed=input_data.get("tank_level_assumed"),
                t10_required=bool(input_data.get("t10_required")),
                dose_basis=input_data.get("dose_basis"),
                delivered_strength=input_data.get("delivered_strength"),
                strength_recorded_at=input_data.get("strength_recorded_at"),
                averaging_basis=input_data.get("averaging_basis"),
                monitoring_frequency=input_data.get("monitoring_frequency"),
                regulation=input_data.get("regulation"),
                limit_sources=input_data.get("limit_sources"),
                evidence=list(evidence),
                tracer_or_basis_changed_since=bool(input_data.get("tracer_or_basis_changed_since")),
                permit_changed_since=bool(input_data.get("permit_changed_since")),
                manual_revised_since=bool(input_data.get("manual_revised_since")),
            )
            basis = TreatmentBasis()
            verdict["interview_status"] = basis.interview_status
            verdict["unfilled_figures"] = basis.unfilled()
            return _envelope("success", result=verdict)
        except Exception as exc:  # noqa: BLE001 — a gate that dies silently is worse
            return _envelope("error", error=f"{type(exc).__name__}: {exc}")
