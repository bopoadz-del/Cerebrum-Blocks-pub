"""Offshore marine operations reasoning gate — store-facing wrapper.

The reasoning layer itself lives in ``app.blocks.offshore_marine.reasoning``
(the gate, the two-source live-state model and the installation-analysis
manifest). This module is the census-facing entrypoint: the block id is
``offshore_marine_reasoning``, the class carries identity metadata, and every
statement is routed through ``gate_answer`` — there is no bypass.

Provenance: structure only. The domain encoding sheet for Offshore Oil & Gas
Marine Operations defines the invariants and the guard; NO INTERVIEW HAS RUN,
so every manifest value is null (``app/blocks/offshore_marine/KNOWN_GAPS.md``).
This block refuses; it does not supply figures it does not have. The verdict
pattern follows ``app.blocks.aviation_grounding_gate`` and the datacentre kit.
"""
from __future__ import annotations

from typing import Any, Dict

from app.blocks.offshore_marine.reasoning import (
    InstallationBasis,
    SpreadState,
    gate_answer,
)
from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {
        "block_id": "offshore_marine_reasoning",
        "status": status,
        "result": result,
        "error": error,
        "detail": detail,
    }


class OffshoreMarineReasoningBlock(UniversalBlock):
    name = "offshore_marine_reasoning"
    version = "1.0.0"
    description = (
        "Deterministic offshore marine operations reasoning gate. Every "
        "statement passes INV-1 (lay tension / strain / stress returned as a "
        "band, never single-sided), INV-2 (allowables carry static_or_dynamic "
        "and region: overbend|sagbend|touchdown|none), INV-3 (envelope figures "
        "carry spread_type s_lay|j_lay|reel_lay|heavy_lift, and never carry "
        "between them), INV-4 (DP / station-keeping answers carry a named "
        "failure_case and a live_state_ref), INV-5 (condition-vs-criterion "
        "comparisons carry horizon, confidence, operation duration, contingency "
        "and window_covers), the ten never-allowed derivations, the vessel "
        "monitoring + manual-log live-state gate, REJECT_AS_PROOF and the "
        "sister-vessel trap. Go/no-go questions are refused BEFORE retrieval. "
        "Blocked and refused statements fail loud; nothing is invented."
    )
    layer = 3
    tags = ["offshore", "marine", "installation", "grounding", "gate", "dp"]
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
            elif isinstance(raw_state, SpreadState):
                state = raw_state
            elif isinstance(raw_state, dict):
                state = SpreadState(
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
                spread_type=input_data.get("spread_type"),
                region=input_data.get("region"),
                static_or_dynamic=input_data.get("static_or_dynamic"),
                failure_case=input_data.get("failure_case"),
                live_state_ref=input_data.get("live_state_ref"),
                forecast=input_data.get("forecast"),
                evidence=list(evidence),
                analysis_changed_since=bool(input_data.get("analysis_changed_since")),
            )
            basis = InstallationBasis()
            verdict["interview_status"] = basis.interview_status
            verdict["unfilled_figures"] = basis.unfilled()
            return _envelope("success", result=verdict)
        except Exception as exc:  # noqa: BLE001 — a gate that dies silently is worse
            return _envelope("error", error=f"{type(exc).__name__}: {exc}")
