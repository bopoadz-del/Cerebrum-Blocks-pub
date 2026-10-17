# Ported (real) from <private-repo> src/<private-repo>/exporters/ifc.py (donor HEAD on disk).
# Intra-package imports are rewritten to relative imports; the code is
# otherwise carried verbatim. DEXPI ingestion is NOT duplicated here: the
# Store's dexpi_ingest block (ported from ingest_dexpi.py) covers ingestion,
# and this package carries the downstream digital thread (graph, routing,
# tables, clash, schedule 4D, generators, PCF, maturity, cascade, exporters).
# The agent/API layers (agent_tools, cli, server, mcp_server) are not ported.
"""IFC4 piping export via ifcopenshell (optional dependency).

Creates IfcProject/Site/Building/Storey structure from DesignVolumes,
IfcPipeSegment per PIPE centreline segment, and IfcPipeFitting for elbows.
Length is encoded in the entity Description as LENGTH_M=<float> for reopen tests.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Optional

from ..graph import TopologyGraph
from ..models import ArtefactDescriptor, ArtefactKind
from ..routing import bore_to_mm, ensure_routes


def _aid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _require_ifcopenshell() -> Any:
    try:
        import ifcopenshell
        import ifcopenshell.api.aggregate
        import ifcopenshell.api.context
        import ifcopenshell.api.root
        import ifcopenshell.api.spatial
        import ifcopenshell.api.unit
        return ifcopenshell
    except ImportError as exc:
        raise ImportError(
            "ifcopenshell is required for IFC export — pip install '<private-repo>[ifc]'"
        ) from exc


def export_ifc4(
    graph: TopologyGraph,
    output_path: Optional[Path] = None,
    routes: Optional[list[dict[str, Any]]] = None,
) -> ArtefactDescriptor:
    """Write an IFC4 file with pipe segments/fittings approximating routes."""
    ifcopenshell = _require_ifcopenshell()
    import ifcopenshell.api.aggregate  # noqa: F811
    import ifcopenshell.api.context  # noqa: F811
    import ifcopenshell.api.root  # noqa: F811
    import ifcopenshell.api.spatial  # noqa: F811
    import ifcopenshell.api.unit  # noqa: F811

    if routes is None:
        ensure_routes(graph)
        routes = list(graph.routes.values())

    model = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.root.create_entity(
        model, ifc_class="IfcProject", name=graph.metadata.get("plant", "<private-repo>")
    )
    ifcopenshell.api.unit.assign_unit(model)
    context = ifcopenshell.api.context.add_context(model, context_type="Model")
    ifcopenshell.api.context.add_context(
        model,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=context,
    )
    site = ifcopenshell.api.root.create_entity(model, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuilding", name="Plant")
    ifcopenshell.api.aggregate.assign_object(model, relating_object=project, products=[site])
    ifcopenshell.api.aggregate.assign_object(model, relating_object=site, products=[building])

    storeys = {}
    for vol in graph.volumes.values():
        storey = ifcopenshell.api.root.create_entity(
            model, ifc_class="IfcBuildingStorey", name=vol.name or vol.id
        )
        ifcopenshell.api.aggregate.assign_object(model, relating_object=building, products=[storey])
        storeys[vol.id] = storey
    if not storeys:
        storey = ifcopenshell.api.root.create_entity(model, ifc_class="IfcBuildingStorey", name="L0")
        ifcopenshell.api.aggregate.assign_object(model, relating_object=building, products=[storey])
        storeys["L0"] = storey
    default_storey = next(iter(storeys.values()))

    segment_count = 0
    fitting_count = 0
    total_length = 0.0

    for route in routes:
        pts = [(p["x"], p["y"], p["z"]) for p in route.get("points") or []]
        bore_m = bore_to_mm(route.get("nominal_bore")) / 1000.0 / 2.0
        line = route.get("line_number") or ""
        for i, (a, b) in enumerate(zip(pts, pts[1:])):
            leng = sum((b[j] - a[j]) ** 2 for j in range(3)) ** 0.5
            if leng < 1e-9:
                continue
            seg = ifcopenshell.api.root.create_entity(
                model,
                ifc_class="IfcPipeSegment",
                name=f"{line}-S{i}",
            )
            seg.Description = (
                f"LENGTH_M={leng:.6f};LINE={line};SERVICE={route.get('service') or ''};"
                f"BORE={route.get('nominal_bore') or ''};SPEC={route.get('piping_spec') or ''};"
                f"WP={route.get('work_package') or ''};TESTPACK={route.get('test_pack') or ''};"
                f"BORE={route.get('nominal_bore') or ''};R={bore_m:.5f};"
                f"START={a[0]:.4f},{a[1]:.4f},{a[2]:.4f};END={b[0]:.4f},{b[1]:.4f},{b[2]:.4f}"
            )
            ifcopenshell.api.spatial.assign_container(
                model, relating_structure=default_storey, products=[seg]
            )
            segment_count += 1
            total_length += leng

        for i in range(1, len(pts) - 1):
            fit = ifcopenshell.api.root.create_entity(
                model,
                ifc_class="IfcPipeFitting",
                name=f"{line}-ELB{i}",
            )
            fit.Description = f"LINE={line};TYPE=ELBOW;CENTRE={pts[i]}"
            ifcopenshell.api.spatial.assign_container(
                model, relating_structure=default_storey, products=[fit]
            )
            fitting_count += 1

    if output_path is None:
        output_path = Path("output/ifc/model.ifc")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(output_path))

    return ArtefactDescriptor(
        id=_aid("IFC"),
        kind=ArtefactKind.IFC,
        status="ready",
        path=str(output_path),
        related_lines=[str(r.get("line_id")) for r in routes if r.get("line_id")],
        payload={
            "segment_count": segment_count,
            "fitting_count": fitting_count,
            "total_length_m": round(total_length, 3),
            "schema": "IFC4",
        },
        message=f"IFC4 written: {segment_count} segments, {fitting_count} fittings",
    )


_LENGTH_RE = re.compile(r"LENGTH_M=([0-9.]+)")


def reopen_counts(path: Path) -> dict[str, Any]:
    ifcopenshell = _require_ifcopenshell()
    model = ifcopenshell.open(str(path))
    segs = model.by_type("IfcPipeSegment")
    fits = model.by_type("IfcPipeFitting")
    total_len = 0.0
    for s in segs:
        desc = s.Description or ""
        m = _LENGTH_RE.search(desc)
        if m:
            total_len += float(m.group(1))
    return {
        "IfcPipeSegment": len(segs),
        "IfcPipeFitting": len(fits),
        "total_length_m": round(total_len, 3),
    }
