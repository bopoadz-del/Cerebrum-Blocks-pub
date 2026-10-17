# Ported (real) from <private-repo> src/<private-repo>/clash.py (donor HEAD on disk).
# Intra-package imports are rewritten to relative imports; the code is
# otherwise carried verbatim. DEXPI ingestion is NOT duplicated here: the
# Store's dexpi_ingest block (ported from ingest_dexpi.py) covers ingestion,
# and this package carries the downstream digital thread (graph, routing,
# tables, clash, schedule 4D, generators, PCF, maturity, cascade, exporters).
# The agent/API layers (agent_tools, cli, server, mcp_server) are not ported.
"""Pipe clash detection via capsule / AABB / cylinder geometry (W7 dropped).

Segment–segment closest points follow Ericson, Real-Time Collision Detection
(§5.1.9). No CAD kernel required.
"""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path
from typing import Any, Optional

from .graph import TopologyGraph
from .models import ArtefactDescriptor, ArtefactKind
from .routing import bore_to_mm, ensure_routes

Point3 = tuple[float, float, float]


def _aid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def segment_distance(
    p1: Point3, q1: Point3, p2: Point3, q2: Point3
) -> tuple[float, Point3, Point3]:
    """Closest points between segments p1–q1 and p2–q2 (Ericson).

    Returns (distance, closest_on_1, closest_on_2).
    """
    # Direction vectors
    d1 = (q1[0] - p1[0], q1[1] - p1[1], q1[2] - p1[2])
    d2 = (q2[0] - p2[0], q2[1] - p2[1], q2[2] - p2[2])
    r = (p1[0] - p2[0], p1[1] - p2[1], p1[2] - p2[2])
    a = d1[0] * d1[0] + d1[1] * d1[1] + d1[2] * d1[2]
    e = d2[0] * d2[0] + d2[1] * d2[1] + d2[2] * d2[2]
    f = d2[0] * r[0] + d2[1] * r[1] + d2[2] * r[2]
    eps = 1e-12

    if a <= eps and e <= eps:
        # both segments degenerate to points
        c1, c2 = p1, p2
    elif a <= eps:
        s = 0.0
        t = max(0.0, min(1.0, f / e))
        c1 = p1
        c2 = (p2[0] + t * d2[0], p2[1] + t * d2[1], p2[2] + t * d2[2])
    else:
        c = d1[0] * r[0] + d1[1] * r[1] + d1[2] * r[2]
        if e <= eps:
            t = 0.0
            s = max(0.0, min(1.0, -c / a))
        else:
            b = d1[0] * d2[0] + d1[1] * d2[1] + d1[2] * d2[2]
            denom = a * e - b * b
            if denom > eps:
                s = max(0.0, min(1.0, (b * f - c * e) / denom))
            else:
                s = 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = max(0.0, min(1.0, -c / a))
            elif t > 1.0:
                t = 1.0
                s = max(0.0, min(1.0, (b - c) / a))
        c1 = (p1[0] + s * d1[0], p1[1] + s * d1[1], p1[2] + s * d1[2])
        c2 = (p2[0] + t * d2[0], p2[1] + t * d2[1], p2[2] + t * d2[2])

    dx, dy, dz = c1[0] - c2[0], c1[1] - c2[1], c1[2] - c2[2]
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    return dist, c1, c2


def capsule_capsule(
    p1: Point3, q1: Point3, r1: float, p2: Point3, q2: Point3, r2: float
) -> dict[str, Any]:
    dist, c1, c2 = segment_distance(p1, q1, p2, q2)
    penetration = (r1 + r2) - dist
    return {
        "distance": dist,
        "penetration": penetration,
        "point_a": c1,
        "point_b": c2,
        "hard": penetration > 1e-9,
    }


def capsule_aabb(
    p: Point3, q: Point3, radius: float, box: tuple[float, float, float, float, float, float]
) -> dict[str, Any]:
    """Approximate capsule vs AABB: sample segment + expand box by radius."""
    xmin, ymin, zmin, xmax, ymax, zmax = box
    # Closest point on segment to AABB centre, then clamp
    best = 1e18
    best_pt = p
    for i in range(21):
        t = i / 20
        pt = (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]), p[2] + t * (q[2] - p[2]))
        cx = min(max(pt[0], xmin), xmax)
        cy = min(max(pt[1], ymin), ymax)
        cz = min(max(pt[2], zmin), zmax)
        d = math.sqrt((pt[0] - cx) ** 2 + (pt[1] - cy) ** 2 + (pt[2] - cz) ** 2)
        if d < best:
            best = d
            best_pt = pt
    penetration = radius - best
    return {
        "distance": best,
        "penetration": penetration,
        "point_a": best_pt,
        "hard": penetration > 1e-9,
    }


def capsule_cylinder(
    p: Point3,
    q: Point3,
    radius: float,
    axis_a: Point3,
    axis_b: Point3,
    cyl_radius: float,
) -> dict[str, Any]:
    dist, c1, c2 = segment_distance(p, q, axis_a, axis_b)
    penetration = (radius + cyl_radius) - dist
    return {
        "distance": dist,
        "penetration": penetration,
        "point_a": c1,
        "point_b": c2,
        "hard": penetration > 1e-9,
    }


def _route_segments(route: dict[str, Any]) -> list[tuple[Point3, Point3, float]]:
    pts = [(p["x"], p["y"], p["z"]) for p in route.get("points") or []]
    r = bore_to_mm(route.get("nominal_bore")) / 2000.0  # approx OD/2 from NB
    segs = []
    for a, b in zip(pts, pts[1:]):
        segs.append((a, b, r))
    return segs


def _connection_nodes(route: dict[str, Any], graph: TopologyGraph) -> set[str]:
    """Nozzle / Connection / from-to ids that terminate this line."""
    nodes: set[str] = set()
    for key in ("from", "to", "from_tag", "to_tag"):
        v = route.get(key)
        if v:
            nodes.add(str(v))
    lid = route.get("line_id")
    if lid and lid in graph.pipelines:
        pipe = graph.pipelines[lid]
        if pipe.from_tag:
            nodes.add(pipe.from_tag)
        if pipe.to_tag:
            nodes.add(pipe.to_tag)
    # Topology FromTo / Connection edges referencing this line
    for edge in graph.from_tos.values():
        if edge.via_line == lid or edge.via_line == route.get("line_number"):
            nodes.add(edge.from_id)
            nodes.add(edge.to_id)
        # Shared Connection endpoint if either endpoint matches route nozzles
        if edge.from_id in nodes or edge.to_id in nodes:
            if edge.connection_type in {"pipe", "nozzle", "connection", "Connection"}:
                nodes.add(edge.from_id)
                nodes.add(edge.to_id)
    return nodes


def _shares_connection_node(a: dict[str, Any], b: dict[str, Any], graph: TopologyGraph) -> bool:
    return bool(_connection_nodes(a, graph) & _connection_nodes(b, graph))


def clash_check(
    graph: TopologyGraph,
    routes: Optional[list[dict[str, Any]]] = None,
    clearance: float = 0.025,
) -> dict[str, Any]:
    """Check hard (dist < r1+r2) and soft (dist < r1+r2+clearance) clashes.

    Skips:
    - pairs that share a connection node (same from/to nozzle or Connection)
    - routes with ``geometry_source == "fabricated"`` (counted in excluded_fabricated)
    - a pipe's own consecutive / intra-line segments (inter-line only)
    """
    if routes is None:
        ensure_routes(graph)
        routes = list(graph.routes.values())

    excluded_fabricated = [
        r.get("line_number") or r.get("line_id")
        for r in routes
        if r.get("geometry_source") == "fabricated"
    ]
    active = [r for r in routes if r.get("geometry_source") != "fabricated"]

    clashes: list[dict[str, Any]] = []
    skipped_shared = 0
    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            if _shares_connection_node(active[i], active[j], graph):
                skipped_shared += 1
                continue
            s1 = _route_segments(active[i])
            s2 = _route_segments(active[j])
            # Inter-line only — never compare a line's own consecutive segments
            for a1, b1, r1 in s1:
                for a2, b2, r2 in s2:
                    dist, c1, c2 = segment_distance(a1, b1, a2, b2)
                    sum_r = r1 + r2
                    if dist < sum_r - 1e-9:
                        kind = "hard"
                        penetration = sum_r - dist
                    elif dist < sum_r + clearance:
                        kind = "soft"
                        penetration = (sum_r + clearance) - dist
                    else:
                        continue
                    clashes.append(
                        {
                            "kind": kind,
                            "distance_m": round(dist, 6),
                            "penetration_m": round(penetration, 6),
                            "location": {
                                "a": [round(x, 4) for x in c1],
                                "b": [round(x, 4) for x in c2],
                            },
                            "tags": [active[i].get("line_number"), active[j].get("line_number")],
                            "line_ids": [active[i].get("line_id"), active[j].get("line_id")],
                        }
                    )
    hard = [c for c in clashes if c["kind"] == "hard"]
    soft = [c for c in clashes if c["kind"] == "soft"]
    return {
        "hard_count": len(hard),
        "soft_count": len(soft),
        "clashes": clashes,
        "hard": hard,
        "soft": soft,
        "clearance_m": clearance,
        "excluded_fabricated": excluded_fabricated,
        "skipped_shared_connection_pairs": skipped_shared,
    }


def generate_clash_report(
    graph: TopologyGraph,
    output_dir: Optional[Path] = None,
    routes: Optional[list[dict[str, Any]]] = None,
) -> ArtefactDescriptor:
    report = clash_check(graph, routes=routes)
    out_path = None
    if output_dir is not None:
        d = Path(output_dir) / "clash"
        d.mkdir(parents=True, exist_ok=True)
        out_path = d / "clash_report.json"
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return ArtefactDescriptor(
        id=_aid("CLASH"),
        kind=ArtefactKind.CLASH,
        status="ready",
        path=str(out_path) if out_path else None,
        related_lines=[lid for c in report["clashes"] for lid in c.get("line_ids") or []],
        payload=report,
        message=f"Clash: {report['hard_count']} hard, {report['soft_count']} soft",
    )
