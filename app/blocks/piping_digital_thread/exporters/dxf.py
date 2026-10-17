# Ported (real) from <private-repo> src/<private-repo>/exporters/dxf.py (donor HEAD on disk).
# Intra-package imports are rewritten to relative imports; the code is
# otherwise carried verbatim. DEXPI ingestion is NOT duplicated here: the
# Store's dexpi_ingest block (ported from ingest_dexpi.py) covers ingestion,
# and this package carries the downstream digital thread (graph, routing,
# tables, clash, schedule 4D, generators, PCF, maturity, cascade, exporters).
# The agent/API layers (agent_tools, cli, server, mcp_server) are not ported.
"""DXF export via ezdxf (optional dependency) — GA plot plan + iso sketch."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

from ..graph import TopologyGraph
from ..models import ArtefactDescriptor, ArtefactKind
from ..routing import ensure_routes, get_route


def _aid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _require_ezdxf() -> Any:
    try:
        import ezdxf
        return ezdxf
    except ImportError as exc:
        raise ImportError("ezdxf is required — pip install '<private-repo>[dxf]'") from exc


def export_ga_dxf(graph: TopologyGraph, output_path: Optional[Path] = None) -> ArtefactDescriptor:
    ezdxf = _require_ezdxf()
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    # layers per volume
    for vol in graph.volumes.values():
        layer = f"VOL_{vol.id}"
        if layer not in doc.layers:
            doc.layers.add(layer)
        msp.add_lwpolyline(
            [(vol.xmin, vol.ymin), (vol.xmax, vol.ymin), (vol.xmax, vol.ymax), (vol.xmin, vol.ymax)],
            close=True,
            dxfattribs={"layer": layer},
        )
    # equipment as points
    if "EQP" not in doc.layers:
        doc.layers.add("EQP")
    for eq in graph.equipment.values():
        vol_opt = graph.volumes.get(eq.volume_id) if eq.volume_id else None
        if vol_opt is None:
            continue
        cx = (vol_opt.xmin + vol_opt.xmax) / 2
        cy = (vol_opt.ymin + vol_opt.ymax) / 2
        msp.add_circle((cx, cy), radius=0.5, dxfattribs={"layer": "EQP"})
        msp.add_text(eq.tag, dxfattribs={"layer": "EQP", "height": 0.4}).set_placement((cx + 0.6, cy))
    # lines
    if "PIP" not in doc.layers:
        doc.layers.add("PIP")
    if "ISO" not in doc.layers:
        doc.layers.add("ISO")
    if "INS" not in doc.layers:
        doc.layers.add("INS")
    ensure_routes(graph)
    for pipe in graph.pipelines.values():
        route = graph.routes.get(pipe.id) or {}
        pts = route.get("points") or []
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            msp.add_line((a["x"], a["y"]), (b["x"], b["y"]), dxfattribs={"layer": "PIP"})

    if output_path is None:
        output_path = Path("output/dxf/plot_plan.dxf")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(output_path))
    entity_count = len(list(msp))
    return ArtefactDescriptor(
        id=_aid("DXF"),
        kind=ArtefactKind.DXF,
        status="ready",
        path=str(output_path),
        payload={"entity_count": entity_count, "kind": "ga"},
        message=f"GA DXF written ({entity_count} entities)",
    )


def export_iso_dxf(
    graph: TopologyGraph, line_id: str, output_path: Optional[Path] = None
) -> ArtefactDescriptor:
    ezdxf = _require_ezdxf()
    pipe = graph.pipelines[line_id]
    route = get_route(graph, line_id)
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    if "ISO" not in doc.layers:
        doc.layers.add("ISO")

    def project(p: dict[str, float]) -> tuple[float, float]:
        # true isometric-ish 2D
        import math
        x, y, z = p["x"], p["y"], p["z"]
        return (x * math.cos(math.radians(30)) - y * math.cos(math.radians(30)),
                x * math.sin(math.radians(30)) + y * math.sin(math.radians(30)) + z)

    pts = [project(p) for p in route.get("points") or []]
    for a, b in zip(pts, pts[1:]):
        msp.add_line(a, b, dxfattribs={"layer": "ISO"})
    if output_path is None:
        safe = pipe.line_number.replace("/", "_")
        output_path = Path(f"output/dxf/{safe}.iso.dxf")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(str(output_path))
    return ArtefactDescriptor(
        id=_aid("DXF"),
        kind=ArtefactKind.DXF,
        status="ready",
        path=str(output_path),
        related_lines=[line_id],
        payload={"entity_count": len(list(msp)), "kind": "iso"},
        message="ISO DXF written",
    )
