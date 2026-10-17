"""Data centre reasoning gate — store-facing wrapper.

The reasoning layer itself lives in ``app.blocks.datacentre.reasoning``
(the gate, the two-source live-state model and the facility_01 design
basis manifest). This module is the census-facing entrypoint: the block
id is ``datacentre_reasoning``, the class carries identity metadata,
and every statement is routed through ``gate_answer`` — no bypass.

Provenance: real — built from the completed domain encoding sheet for
facility_01 (see ``app/blocks/datacentre/manifest.yaml``); the verdict
pattern follows ``app.blocks.aviation_grounding_gate.py``.
"""
from __future__ import annotations

from typing import Any, Dict

from app.blocks.datacentre.reasoning import (
    DesignBasis,
    ResilienceState,
    gate_answer,
)
from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "datacentre_reasoning",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


class DatacentreReasoningBlock(UniversalBlock):
    name = "datacentre_reasoning"
    version = "1.0.0"
    description = (
        "Deterministic data centre reasoning gate seeded with the facility_01 "
        "design basis. Every statement passes INV-1 (tested claims carry "
        "commissioning_level + load_pct + failure_scenario), INV-2 (resilience "
        "claims carry as_designed|as_built|as_currently_operating), INV-3 "
        "(capacity claims carry design|installed|available_after_redundancy), "
        "INV-4 (readiness declarations refused before retrieval), the "
        "never-allowed derivation guard, the BMS + manual-log live-state gate, "
        "REJECT_AS_PROOF and the tier trap. Blocked and refused statements fail "
        "loud; nothing is invented."
    )
    layer = 3
    tags = ["datacentre", "resilience", "grounding", "gate", "facility"]
    requires: list = []

    async def process(self, input_data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            query = str(input_data.get("query") or params.get("query") or "").strip()
            answer = str(input_data.get("answer") or params.get("answer") or "").strip()
            if not query or not answer:
                return _envelope("refused", error="query and answer are required")

            live_state = input_data.get("live_state")
            if live_state is None:
                state = None
            elif isinstance(live_state, ResilienceState):
                state = live_state
            elif isinstance(live_state, dict):
                state = ResilienceState(
                    bms=live_state.get("bms"),
                    manual_log=live_state.get("manual_log"),
                    fetched_at=live_state.get("fetched_at"),
                )
            else:
                return _envelope(
                    "refused",
                    error="live_state must be a ResilienceState or a dict "
                    "{bms, manual_log, fetched_at}",
                )

            verdict = gate_answer(
                query,
                answer,
                live_state=state,
                basis=input_data.get("basis") or params.get("basis"),
                evidence=input_data.get("evidence") or params.get("evidence"),
                test_modified_since_ist=bool(input_data.get("test_modified_since_ist", False)),
            )
            if verdict["verdict"] in ("block", "refused"):
                return _envelope("refused", error=verdict.get("blocked_reason"), result=verdict)
            return _envelope("ok", result=verdict)
        except Exception as exc:  # fail loud, never silent
            return _envelope("error", error=str(exc))


__all__ = ["DatacentreReasoningBlock", "DesignBasis", "ResilienceState", "gate_answer"]
