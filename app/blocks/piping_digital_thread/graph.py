# Ported (real) from <private-repo> src/<private-repo>/graph.py (donor HEAD on disk).
# Intra-package imports are rewritten to relative imports; the code is
# otherwise carried verbatim. DEXPI ingestion is NOT duplicated here: the
# Store's dexpi_ingest block (ported from ingest_dexpi.py) covers ingestion,
# and this package carries the downstream digital thread (graph, routing,
# tables, clash, schedule 4D, generators, PCF, maturity, cascade, exporters).
# The agent/API layers (agent_tools, cli, server, mcp_server) are not ported.
"""Topology graph: tags, lines, from-to, battery limits, spatial joins."""

from __future__ import annotations

from typing import Any, Optional

from .models import (
    BatteryLimit,
    DesignVolume,
    Equipment,
    FromTo,
    Instrument,
    Nozzle,
    Pipeline,
    Sheet,
    System,
    Tag,
    WorkPackage,
)


class TopologyGraph:
    """In-memory digital-thread graph linking P&ID entities to layout/AWP."""

    def __init__(self) -> None:
        self.tags: dict[str, Tag] = {}
        self.pipelines: dict[str, Pipeline] = {}
        self.from_tos: dict[str, FromTo] = {}
        self.battery_limits: dict[str, BatteryLimit] = {}
        self.sheets: dict[str, Sheet] = {}
        self.equipment: dict[str, Equipment] = {}
        self.nozzles: dict[str, Nozzle] = {}
        self.instruments: dict[str, Instrument] = {}
        self.volumes: dict[str, DesignVolume] = {}
        self.systems: dict[str, System] = {}
        self.work_packages: dict[str, WorkPackage] = {}
        self.unmatched_tags: list[str] = []
        self.metadata: dict[str, Any] = {}
        # Shared A* geometry: line_id → RouteResult dict (points, length_m, accuracy, …).
        # Populated once by generate_routes_astar; all artefacts MUST read this.
        self.routes: dict[str, dict[str, Any]] = {}

    # -- mutators -----------------------------------------------------------

    def add_tag(self, tag: Tag) -> None:
        self.tags[tag.id] = tag

    def add_pipeline(self, pipe: Pipeline) -> None:
        self.pipelines[pipe.id] = pipe

    def add_from_to(self, edge: FromTo) -> None:
        self.from_tos[edge.id] = edge
        if not edge.matched:
            if edge.from_id not in self.tags and edge.from_id not in self.unmatched_tags:
                self.unmatched_tags.append(edge.from_id)
            if edge.to_id not in self.tags and edge.to_id not in self.unmatched_tags:
                self.unmatched_tags.append(edge.to_id)

    def add_battery_limit(self, bl: BatteryLimit) -> None:
        self.battery_limits[bl.id] = bl

    def add_sheet(self, sheet: Sheet) -> None:
        self.sheets[sheet.id] = sheet

    def add_equipment(self, eq: Equipment) -> None:
        self.equipment[eq.id] = eq

    def add_nozzle(self, nz: Nozzle) -> None:
        self.nozzles[nz.id] = nz

    def add_instrument(self, inst: Instrument) -> None:
        self.instruments[inst.id] = inst

    def add_volume(self, vol: DesignVolume) -> None:
        self.volumes[vol.id] = vol

    def add_system(self, sys: System) -> None:
        self.systems[sys.id] = sys

    def add_work_package(self, wp: WorkPackage) -> None:
        self.work_packages[wp.id] = wp

    # -- queries ------------------------------------------------------------

    def get_tag(self, tag_id: str) -> Optional[Tag]:
        return self.tags.get(tag_id)

    def neighbors(self, tag_id: str) -> list[str]:
        """Return connected tag ids via FromTo edges."""
        result: list[str] = []
        for edge in self.from_tos.values():
            if edge.from_id == tag_id:
                result.append(edge.to_id)
            elif edge.to_id == tag_id:
                result.append(edge.from_id)
        return result

    def lines_for_tag(self, tag_id: str) -> list[Pipeline]:
        out: list[Pipeline] = []
        for p in self.pipelines.values():
            if p.from_tag == tag_id or p.to_tag == tag_id or tag_id in p.component_tags:
                out.append(p)
        return out

    def tags_in_volume(self, volume_id: str) -> list[Tag]:
        return [t for t in self.tags.values() if t.volume_id == volume_id]

    def tags_by_discipline(self, discipline: str) -> list[Tag]:
        return [t for t in self.tags.values() if t.discipline.value == discipline]

    def connectivity_summary(self) -> dict[str, Any]:
        matched = sum(1 for e in self.from_tos.values() if e.matched)
        unmatched_edges = sum(1 for e in self.from_tos.values() if not e.matched)
        return {
            "tag_count": len(self.tags),
            "pipeline_count": len(self.pipelines),
            "from_to_count": len(self.from_tos),
            "matched_joins": matched,
            "unmatched_joins": unmatched_edges,
            "unmatched_tags": list(self.unmatched_tags),
            "battery_limit_count": len(self.battery_limits),
            "sheet_count": len(self.sheets),
            "equipment_count": len(self.equipment),
            "volume_count": len(self.volumes),
            "system_count": len(self.systems),
            "work_package_count": len(self.work_packages),
        }

    def query(self, **filters: Any) -> dict[str, Any]:
        """Flexible query used by agent_tools.query_graph."""
        result: dict[str, Any] = {"filters": filters}
        if "tag_id" in filters:
            t = self.get_tag(filters["tag_id"])
            result["tag"] = t.model_dump() if t else None
            if t:
                result["neighbors"] = self.neighbors(t.id)
                result["lines"] = [p.model_dump() for p in self.lines_for_tag(t.id)]
        if "discipline" in filters:
            result["tags"] = [
                t.model_dump() for t in self.tags_by_discipline(filters["discipline"])
            ]
        if "volume_id" in filters:
            result["tags"] = [
                t.model_dump() for t in self.tags_in_volume(filters["volume_id"])
            ]
        if "line_id" in filters:
            p = self.pipelines.get(filters["line_id"])
            result["pipeline"] = p.model_dump() if p else None
        if "summary" in filters and filters["summary"]:
            result["summary"] = self.connectivity_summary()
        if not filters:
            result["summary"] = self.connectivity_summary()
        return result

    def revise_tag(self, tag_id: str, updates: dict[str, Any]) -> Tag:
        tag = self.tags.get(tag_id)
        if tag is None:
            raise KeyError(f"Tag not found: {tag_id}")
        data = tag.model_dump()
        for k, v in updates.items():
            if k in data and k not in ("id",):
                if k == "identity" and isinstance(v, dict):
                    data["identity"] = {**(data.get("identity") or {}), **v}
                elif k == "engineering" and isinstance(v, dict):
                    data["engineering"] = {**(data.get("engineering") or {}), **v}
                elif k == "metadata" and isinstance(v, dict):
                    data["metadata"] = {**(data.get("metadata") or {}), **v}
                else:
                    data[k] = v
        revised = Tag.model_validate(data)
        self.tags[tag_id] = revised
        # Keep equipment in sync if present
        for eq in self.equipment.values():
            if eq.tag == tag_id or eq.id == tag_id:
                eq_data = eq.model_dump()
                if "identity" in updates and isinstance(updates["identity"], dict):
                    eq_data["identity"] = {**(eq_data.get("identity") or {}), **updates["identity"]}
                if "engineering" in updates and isinstance(updates["engineering"], dict):
                    eq_data["engineering"] = {
                        **(eq_data.get("engineering") or {}),
                        **updates["engineering"],
                    }
                if "name" in updates:
                    pass
                self.equipment[eq.id] = Equipment.model_validate(eq_data)
        return revised

    def revise_pipeline(self, line_id: str, updates: dict[str, Any]) -> Pipeline:
        pipe = self.pipelines.get(line_id)
        if pipe is None:
            raise KeyError(f"Pipeline not found: {line_id}")
        data = pipe.model_dump()
        for k, v in updates.items():
            if k in data and k != "id":
                if k == "metadata" and isinstance(v, dict):
                    data["metadata"] = {**(data.get("metadata") or {}), **v}
                else:
                    data[k] = v
        revised = Pipeline.model_validate(data)
        self.pipelines[line_id] = revised
        return revised
