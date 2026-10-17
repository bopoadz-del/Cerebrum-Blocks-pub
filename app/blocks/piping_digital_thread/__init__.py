"""Piping digital thread — the <private-repo> EPC digital-thread domain core,
ported as a Store block package.

Provenance: real — ported from <private-repo> src/<private-repo>/ (donor HEAD on
disk): models.py, graph.py, routing.py, tables.py, clash.py, schedule_4d.py,
generators.py, cascade.py, maturity.py, pcf_reader.py, pcf_strict.py and
exporters/{dxf,ifc}.py. Intra-package imports are rewritten to relative
imports; the donor code is otherwise carried verbatim.

Honest scope (matching the donor's own WALLS.md discipline): DEXPI/P&ID
ingestion is NOT duplicated here — the Store's dexpi_ingest block (ported
from <private-repo> ingest_dexpi.py) covers ingestion, and this package carries
the downstream thread: topology graph, A* routing with obstacle avoidance,
pipe tables (ASME B36.10-style), capsule/AABB/cylinder clash checking
(Ericson §5.1.9), 4D schedule co-activity/look-ahead, PCF/GA/SVG/ISO
generation, change cascade (dirty-set), and maturity assessment. The
agent/API layers (agent_tools, cli, server, mcp_server) are not ported.

The block facade builds a TopologyGraph from JSON dicts and dispatches to
the ported functions; every action returns a structured envelope.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.core.universal_base import UniversalBlock

from .models import (
    BatteryLimit,
    ChangeEvent,
    DesignVolume,
    DirtySet,
    Equipment,
    FromTo,
    Instrument,
    JobPipeline,
    JobStage,
    MaturityLevel,
    Nozzle,
    Pipeline,
    ScheduleActivity,
    Sheet,
    StageStatus,
    Subsystem,
    System,
    Tag,
    TestPack,
    WorkPackage,
)
from .graph import TopologyGraph
from .tables import (
    flange_bolts,
    hydrotest_pressure_barg,
    mass_per_m,
    od_mm,
    support_span_m,
    wall_thickness_mm,
)
from .routing import generate_routes_astar
from .clash import clash_check, generate_clash_report, segment_distance
from .schedule_4d import Schedule4D
from .maturity import assess_maturity
from .cascade import CascadeEngine

__version__ = "0.1.0"

_ENTITY_KINDS = {
    "tags": Tag, "pipelines": Pipeline, "from_tos": FromTo, "battery_limits": BatteryLimit,
    "sheets": Sheet, "equipment": Equipment, "nozzles": Nozzle, "instruments": Instrument,
    "volumes": DesignVolume, "systems": System, "subsystems": Subsystem,
    "work_packages": WorkPackage, "test_packs": TestPack,
}


def build_graph(spec: Dict[str, Any]) -> TopologyGraph:
    """Build a TopologyGraph from a JSON dict (the donor's model constructors)."""
    graph = TopologyGraph()
    for kind, model in _ENTITY_KINDS.items():
        for raw in spec.get(kind) or []:
            if not isinstance(raw, dict):
                continue
            entity = model.model_validate(raw)
            if kind == "tags":
                graph.add_tag(entity)
            elif kind == "pipelines":
                graph.add_pipeline(entity)
            elif kind == "from_tos":
                graph.add_from_to(entity)
            elif kind == "battery_limits":
                graph.add_battery_limit(entity)
            elif kind == "sheets":
                graph.add_sheet(entity)
            elif kind == "equipment":
                graph.add_equipment(entity)
            elif kind == "nozzles":
                graph.add_nozzle(entity)
            elif kind == "instruments":
                graph.add_instrument(entity)
            elif kind == "volumes":
                graph.add_volume(entity)
            elif kind == "systems":
                graph.add_system(entity)
            elif kind == "subsystems":
                graph.subsystems[entity.id] = entity
            elif kind == "work_packages":
                graph.add_work_package(entity)
            elif kind == "test_packs":
                graph.test_packs[entity.id] = entity
    if isinstance(spec.get("metadata"), dict):
        graph.metadata.update(spec["metadata"])
    return graph


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "piping_digital_thread", "status": status, "result": result, "error": error, "detail": detail}


def _artefact_dict(art) -> Dict[str, Any]:
    return {
        "id": art.id,
        "kind": art.kind.value if hasattr(art.kind, "value") else str(art.kind),
        "status": art.status,
        "path": art.path,
        "related_lines": art.related_lines,
        "payload": art.payload,
        "message": art.message,
    }


class PipingDigitalThreadBlock(UniversalBlock):
    """<private-repo> EPC piping digital-thread core, ported as a Store block."""

    name = "piping_digital_thread"
    version = "0.1.0"
    description = (
        "real: EPC piping digital-thread core ported from <private-repo> "
        "src/<private-repo>/{graph,routing,tables,clash,schedule_4d,generators,"
        "cascade,maturity,pcf_reader,pcf_strict,models}.py + exporters/. "
        "Topology graph, A* routing with obstacle avoidance, pipe tables, "
        "capsule/AABB/cylinder clash checking (Ericson §5.1.9), 4D "
        "co-activity/look-ahead, PCF/GA generation, change cascade (dirty-set) "
        "and maturity assessment. DEXPI ingestion stays with the dexpi_ingest "
        "block; agent/API layers (agent_tools/cli/server/mcp_server) are not "
        "ported."
    )
    layer = 3
    tags = ["epc", "piping", "digital-thread", "dexpi", "clash", "routing", "4d", "pcf", "<private-repo>"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "summary", "graph": {"pipelines": [], "equipment": []}}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._graphs: Dict[str, TopologyGraph] = {}

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "summary")).lower()
        try:
            if action in ("build_graph", "summary", "route_astar", "clash_check", "tables", "pcf_text", "schedule4d", "maturity", "cascade", "clash_report"):
                return self._dispatch(action, payload)
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["build_graph", "summary", "route_astar", "clash_check", "clash_report", "tables", "pcf_text", "schedule4d", "maturity", "cascade"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    # -- internals ---------------------------------------------------------

    def _graph(self, payload: Dict[str, Any]) -> TopologyGraph:
        spec = payload.get("graph")
        if not isinstance(spec, dict):
            raise ValueError("action requires a 'graph' spec object")
        return build_graph(spec)

    def _dispatch(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if action == "build_graph":
            graph = self._graph(payload)
            summary = graph.connectivity_summary()
            return _envelope("ok", {"summary": summary, "routes": len(graph.routes)})
        if action == "summary":
            return _envelope("ok", {"summary": self._graph(payload).connectivity_summary()})
        if action == "route_astar":
            graph = self._graph(payload)
            art = generate_routes_astar(
                graph,
                support_spacing=float(payload.get("support_spacing", 3.0)),
                grid=float(payload.get("grid", 0.5)),
            )
            return _envelope("ok", {"artefact": _artefact_dict(art), "route_count": len(graph.routes)})
        if action == "clash_check":
            graph = self._graph(payload)
            routes = payload.get("routes")
            if routes is not None and not isinstance(routes, list):
                return _envelope("error", error="'routes' must be a list of route dicts")
            report = clash_check(graph, routes=routes, clearance=float(payload.get("clearance", 0.025)))
            return _envelope("ok", {"report": report})
        if action == "clash_report":
            graph = self._graph(payload)
            art = generate_clash_report(graph)
            return _envelope("ok", {"artefact": _artefact_dict(art)})
        if action == "tables":
            return self._tables(payload)
        if action == "pcf_text":
            graph = self._graph(payload)
            line_id = str(payload.get("line_id", ""))
            if line_id not in graph.pipelines:
                return _envelope("error", error=f"pipeline not found: {line_id}", detail={"known": sorted(graph.pipelines)})
            return _envelope("ok", {"pcf": write_pcf_text(graph, line_id)})
        if action == "schedule4d":
            return self._schedule4d(payload)
        if action == "maturity":
            return _envelope("ok", {"maturity": assess_maturity(self._graph(payload))})
        if action == "cascade":
            return self._cascade(payload)
        return _envelope("error", error=f"unhandled action: {action}")

    def _tables(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        fn = str(payload.get("fn", ""))
        bore = payload.get("nominal_bore")
        out: Dict[str, Any] = {"fn": fn, "nominal_bore": bore}
        if fn == "od_mm":
            out["od_mm"] = od_mm(bore)
        elif fn == "wall_thickness_mm":
            out["wall_thickness_mm"] = wall_thickness_mm(bore, str(payload.get("schedule", "40")))
        elif fn == "mass_per_m":
            out["mass_per_m"] = mass_per_m(bore, str(payload.get("schedule", "40")))
        elif fn == "support_span_m":
            out["support_span_m"] = support_span_m(bore)
        elif fn == "hydrotest_pressure_barg":
            out["hydrotest_pressure_barg"] = hydrotest_pressure_barg(payload.get("design_pressure_barg"))
        elif fn == "flange_bolts":
            out["flange_bolts"] = flange_bolts(bore, int(payload.get("flange_class", 150)))
        elif fn == "all":
            out["od_mm"] = od_mm(bore)
            out["wall_thickness_mm"] = wall_thickness_mm(bore, str(payload.get("schedule", "40")))
            out["mass_per_m"] = mass_per_m(bore, str(payload.get("schedule", "40")))
            out["support_span_m"] = support_span_m(bore)
        else:
            return _envelope("error", error=f"unknown tables fn: {fn}", detail={"known": ["od_mm", "wall_thickness_mm", "mass_per_m", "support_span_m", "hydrotest_pressure_barg", "flange_bolts", "all"]})
        return _envelope("ok", {"tables": out})

    def _schedule4d(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        graph = self._graph(payload)
        s4d = Schedule4D(graph)
        activities = payload.get("activities")
        if not isinstance(activities, list) or not activities:
            return _envelope("error", error="schedule4d requires an 'activities' list")
        schedule_payload: Dict[str, Any] = {"activities": activities}
        if payload.get("schedule_date"):
            schedule_payload["schedule_date"] = payload.get("schedule_date")
        count = s4d.load_json(schedule_payload)
        mode = str(payload.get("mode", "co_activity"))
        if mode == "co_activity":
            return _envelope("ok", {"activities_loaded": count, "co_activity": s4d.co_activity_check()})
        if mode == "look_ahead":
            weeks = int(payload.get("weeks", 3))
            from_date = payload.get("from_date")
            if from_date is not None:
                from_date = str(from_date)
            return _envelope("ok", {"activities_loaded": count, "look_ahead": s4d.look_ahead(weeks=weeks, from_date=from_date)})
        return _envelope("error", error=f"unknown schedule4d mode: {mode}", detail={"known": ["co_activity", "look_ahead"]})

    def _cascade(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        graph = self._graph(payload)
        engine = CascadeEngine(graph)
        change = payload.get("change")
        if not isinstance(change, dict) or not change.get("entity_type"):
            return _envelope("error", error="cascade requires a 'change' {entity_type, entity_id, action?}")
        event = engine.record_change(
            str(change.get("entity_type")),
            str(change.get("entity_id")),
            action=str(change.get("action", "revise")),
            details=change.get("details") if isinstance(change.get("details"), dict) else None,
        )
        dirty = engine.dirty_summary()
        return _envelope("ok", {"event_id": event.id, "dirty": dirty})


# pcf generation lives in generators.py (imported lazily by the dispatcher)
from .generators import write_pcf_text  # noqa: E402
