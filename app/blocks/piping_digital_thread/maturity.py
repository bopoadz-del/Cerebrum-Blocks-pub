# Ported (real) from <private-repo> src/<private-repo>/maturity.py (donor HEAD on disk).
# Intra-package imports are rewritten to relative imports; the code is
# otherwise carried verbatim. DEXPI ingestion is NOT duplicated here: the
# Store's dexpi_ingest block (ported from ingest_dexpi.py) covers ingestion,
# and this package carries the downstream digital thread (graph, routing,
# tables, clash, schedule 4D, generators, PCF, maturity, cascade, exporters).
# The agent/API layers (agent_tools, cli, server, mcp_server) are not ported.
"""FEED / L1..L4 / IFC maturity gates."""

from __future__ import annotations

from typing import Any, Optional

from .graph import TopologyGraph
from .models import (
    MATURITY_ORDER,
    JobPipeline,
    JobStage,
    MaturityLevel,
    StageStatus,
)


def maturity_index(level: MaturityLevel) -> int:
    return MATURITY_ORDER.index(level)


def meets_or_exceeds(current: MaturityLevel, required: MaturityLevel) -> bool:
    return maturity_index(current) >= maturity_index(required)


def assess_maturity(graph: TopologyGraph, job: Optional[JobPipeline] = None) -> dict[str, Any]:
    """Heuristic maturity assessment from graph completeness + stage status."""
    summary = graph.connectivity_summary()
    score_bits: list[str] = []
    level = MaturityLevel.FEED

    if summary["tag_count"] > 0 and summary["sheet_count"] > 0:
        level = MaturityLevel.L1
        score_bits.append("tags+sheets")
    if summary["pipeline_count"] > 0 and summary["from_to_count"] > 0:
        level = MaturityLevel.L2
        score_bits.append("topology")
    if summary["volume_count"] > 0 and summary["equipment_count"] > 0:
        level = MaturityLevel.L3_60
        score_bits.append("layout+equipment")
    if (
        summary["matched_joins"] > 0
        and summary["unmatched_joins"] == 0
        and summary["work_package_count"] > 0
    ):
        level = MaturityLevel.L4_90
        score_bits.append("joins+WPs")
    # IFC only if explicitly advanced + no unmatched + battery limits reviewed
    if (
        level == MaturityLevel.L4_90
        and summary["battery_limit_count"] > 0
        and summary["unmatched_tags"] == []
        and job is not None
        and all(s.status == StageStatus.DONE for s in job.stages)
        and job.target_maturity == MaturityLevel.IFC
    ):
        level = MaturityLevel.IFC
        score_bits.append("ifc-ready")

    if job is not None:
        job.current_maturity = level

    # Data-derived gate reasons (not sticky flags)
    fabricated = [
        lid
        for lid, r in (graph.routes or {}).items()
        if (r or {}).get("geometry_source") == "fabricated"
    ]
    unmatched_opc = [
        e.id
        for e in graph.from_tos.values()
        if (e.connection_type or "").startswith("opc") and not e.matched
    ]
    design_pressure_ok = any(
        (p.metadata or {}).get("DesignPressure") not in (None, "")
        for p in graph.pipelines.values()
    )
    reasons = {
        "fabricated_count": len(fabricated),
        "unmatched_opc_count": len(unmatched_opc),
        "design_pressure_present": design_pressure_ok,
        "clash_hard": 0,  # filled by caller when clash run; default 0 if routes clean
        "factors": score_bits,
    }
    if fabricated:
        level = min(level, MaturityLevel.L3_60, key=lambda x: MATURITY_ORDER.index(x))
        reasons["blocks_ifc"] = "fabricated_geometry"
    return {
        "maturity": level.value,
        "level": level,
        "factors": score_bits,
        "reasons": reasons,
        "gates": reasons,
        "summary": summary,
        "target": job.target_maturity.value if job else None,
    }


class MaturityGateError(PermissionError):
    """Raised when an export/action is refused due to insufficient maturity."""


def maturity_check(
    current: MaturityLevel,
    required: MaturityLevel = MaturityLevel.IFC,
    action: str = "export",
    graph: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Check whether current maturity allows an action.
    Refuses IFC-grade export if maturity < IFC.
    Refuses IFC/PCF export when any line has fabricated geometry.
    """
    allowed = meets_or_exceeds(current, required)
    result: dict[str, Any] = {
        "allowed": allowed,
        "current": current.value,
        "required": required.value,
        "action": action,
    }
    fabricated: list[str] = []
    if graph is not None:
        from .routing import ensure_routes, get_route

        ensure_routes(graph)
        for p in graph.pipelines.values():
            r = get_route(graph, p.id)
            if r.get("geometry_source") == "fabricated":
                fabricated.append(p.line_number)
    result["fabricated_lines"] = fabricated
    action_l = action.lower()
    if fabricated and any(k in action_l for k in ("ifc", "pcf", "export")):
        allowed = False
        result["allowed"] = False
        result["message"] = (
            f"Refused {action}: fabricated geometry on lines {fabricated}"
        )
        result["error"] = "MaturityGateError"
        return result
    if not allowed:
        result["message"] = (
            f"Refused {action} as {required.value}-grade: "
            f"current maturity is {current.value} (< {required.value})"
        )
        result["error"] = "MaturityGateError"
    else:
        result["message"] = f"{action} permitted at {current.value}"
    return result


def assert_maturity(
    current: MaturityLevel,
    required: MaturityLevel = MaturityLevel.IFC,
    action: str = "export",
    graph: Optional[Any] = None,
) -> None:
    check = maturity_check(current, required, action, graph=graph)
    if not check["allowed"]:
        raise MaturityGateError(check["message"])


def mark_stage_done(job: JobPipeline, stage: JobStage, message: str = "Done") -> None:
    from datetime import datetime, timezone

    st = job.stage_state(stage)
    st.status = StageStatus.DONE
    st.message = message
    st.updated_at = datetime.now(timezone.utc)
