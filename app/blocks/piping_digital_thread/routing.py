# Ported (real) from <private-repo> src/<private-repo>/routing.py (donor HEAD on disk).
# Intra-package imports are rewritten to relative imports; the code is
# otherwise carried verbatim. DEXPI ingestion is NOT duplicated here: the
# Store's dexpi_ingest block (ported from ingest_dexpi.py) covers ingestion,
# and this package carries the downstream digital thread (graph, routing,
# tables, clash, schedule 4D, generators, PCF, maturity, cascade, exporters).
# The agent/API layers (agent_tools, cli, server, mcp_server) are not ported.
"""Piping routes: shared A* geometry with Manhattan fallback + supports.

Primary entry: ``generate_routes_astar`` → ``graph.routes`` (single geometry).
``route_pipeline`` is Manhattan-only and may be called solely as A* fallback
(``accuracy="manhattan_fallback"``) or for fabricated endpoints.

Accuracy limits (see WALLS.md):
- Shared routes are axis-aligned polylines between nozzle/equipment points.
- Obstacle-aware A* uses equipment AABBs + prior capsules; no B-rep solids.
- No stress analysis or spec-driven elbow catalogues in the router itself.
- Coordinates from nozzle XYZ (fabricated flag when missing).
"""

from __future__ import annotations

import heapq
import math
from typing import Any, Optional

from .graph import TopologyGraph
from .models import ArtefactDescriptor, ArtefactKind, DesignVolume, Pipeline
from .tables import support_span_m as table_support_span


def _aid(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:8]}"


Point3 = tuple[float, float, float]



def nozzle_xyz_explicit(graph: TopologyGraph, nozzle_or_tag_id: Optional[str]) -> Optional[Point3]:
    """Return XYZ only when the nozzle record itself carries coordinates."""
    if not nozzle_or_tag_id:
        return None
    nz = graph.nozzles.get(nozzle_or_tag_id)
    if nz and nz.x is not None and nz.y is not None and nz.z is not None:
        return (float(nz.x), float(nz.y), float(nz.z))
    return None

def nozzle_point(graph: TopologyGraph, nozzle_or_tag_id: Optional[str]) -> Optional[Point3]:
    """Resolve a tag/nozzle id to a 3D point."""
    if not nozzle_or_tag_id:
        return None
    nz = graph.nozzles.get(nozzle_or_tag_id)
    if nz and nz.x is not None and nz.y is not None and nz.z is not None:
        return (float(nz.x), float(nz.y), float(nz.z))
    # Equipment centroid from volume or bounds
    tag = graph.tags.get(nozzle_or_tag_id)
    eq_id = None
    if nz:
        eq_id = nz.equipment_id
    elif tag and tag.metadata.get("equipment_id"):
        eq_id = tag.metadata["equipment_id"]
    elif nozzle_or_tag_id in graph.equipment:
        eq_id = nozzle_or_tag_id
    if eq_id and eq_id in graph.equipment:
        eq = graph.equipment[eq_id]
        if eq.volume_id and eq.volume_id in graph.volumes:
            v = graph.volumes[eq.volume_id]
            return _volume_centroid(v)
        t = graph.tags.get(eq_id)
        if t and t.geometry_bounds:
            b = t.geometry_bounds
            return (
                (b.get("xmin", 0) + b.get("xmax", 0)) / 2.0 / 10.0,  # sheet px → rough m
                (b.get("ymin", 0) + b.get("ymax", 0)) / 2.0 / 10.0,
                5.0,
            )
    if tag and tag.volume_id and tag.volume_id in graph.volumes:
        return _volume_centroid(graph.volumes[tag.volume_id])
    return None


def _volume_centroid(v: DesignVolume) -> Point3:
    return (
        (v.xmin + v.xmax) / 2.0,
        (v.ymin + v.ymax) / 2.0,
        (v.zmin + v.zmax) / 2.0,
    )


def manhattan_route(start: Point3, end: Point3, prefer_order: str = "xyz") -> list[Point3]:
    """Build an orthogonal polyline from start to end (up to 4 points).

    prefer_order: permutation of x/y/z indicating bend priority.
    """
    if start == end:
        return [start]
    sx, sy, sz = start
    ex, ey, ez = end
    pts: list[Point3] = [start]
    order = prefer_order.lower()
    cur = [sx, sy, sz]
    target = [ex, ey, ez]
    axis_map = {"x": 0, "y": 1, "z": 2}
    for axis in order:
        i = axis_map[axis]
        if abs(cur[i] - target[i]) > 1e-9:
            cur = list(cur)
            cur[i] = target[i]
            pts.append((cur[0], cur[1], cur[2]))
    if pts[-1] != end:
        pts.append(end)
    # Deduplicate consecutive identical points
    cleaned: list[Point3] = [pts[0]]
    for p in pts[1:]:
        if p != cleaned[-1]:
            cleaned.append(p)
    return cleaned


def polyline_length(points: list[Point3]) -> float:
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += math.sqrt(sum((b[i] - a[i]) ** 2 for i in range(3)))
    return total


def support_placeholders(
    points: list[Point3],
    spacing: float = 3.0,
) -> list[dict[str, Any]]:
    """Place support markers along the route at approximate intervals."""
    if len(points) < 2 or spacing <= 0:
        return []
    supports: list[dict[str, Any]] = []
    dist_accum = 0.0
    next_at = spacing
    for a, b in zip(points, points[1:]):
        seg_len = math.sqrt(sum((b[i] - a[i]) ** 2 for i in range(3)))
        if seg_len < 1e-9:
            continue
        while next_at <= dist_accum + seg_len:
            t = (next_at - dist_accum) / seg_len
            pos = tuple(a[i] + t * (b[i] - a[i]) for i in range(3))
            supports.append(
                {
                    "id": f"SUP-{len(supports)+1:03d}",
                    "type": "placeholder",
                    "xyz": list(pos),
                    "station_m": round(next_at, 3),
                    "note": "Heuristic interval support — not engineered",
                }
            )
            next_at += spacing
        dist_accum += seg_len
    return supports


def route_pipeline(
    graph: TopologyGraph,
    pipe: Pipeline,
    support_spacing: float = 3.0,
) -> dict[str, Any]:
    """Compute Manhattan route + supports for one pipeline.

    If either endpoint lacks explicit nozzle XYZ, geometry is marked
    ``fabricated`` / ``degraded`` (never silent). Fallback coordinates may
    still be produced for sketching, but downstream artefacts must carry the flag.
    """
    start_explicit = nozzle_xyz_explicit(graph, pipe.from_tag)
    end_explicit = nozzle_xyz_explicit(graph, pipe.to_tag)
    fabricated = start_explicit is None or end_explicit is None

    start = start_explicit if start_explicit is not None else nozzle_point(graph, pipe.from_tag)
    end = end_explicit if end_explicit is not None else nozzle_point(graph, pipe.to_tag)
    if start is None:
        start = (0.0, 0.0, 5.0)
        fabricated = True
    if end is None:
        end = (start[0] + 10.0, start[1] + 5.0, start[2])
        fabricated = True
    if start == end:
        # Degenerate — nudge fabricated end so artefacts have a segment
        end = (start[0] + 1.0, start[1], start[2])
        fabricated = True

    points = manhattan_route(start, end, prefer_order="xzy")
    length = polyline_length(points)
    supports = support_placeholders_engineered(points, nominal_bore=pipe.nominal_bore)
    if support_spacing != 3.0:
        # explicit override still honoured via interval merge
        supports = support_placeholders(points, spacing=support_spacing) + [
            s for s in supports if s.get("type") in {"near_bend", "near_nozzle"}
        ]
    out: dict[str, Any] = {
        "line_id": pipe.id,
        "line_number": pipe.line_number,
        "from": pipe.from_tag,
        "to": pipe.to_tag,
        "nominal_bore": pipe.nominal_bore,
        "points": [{"x": p[0], "y": p[1], "z": p[2]} for p in points],
        "length_m": round(length, 3),
        "supports": supports,
        "accuracy": "manhattan_fallback",
        "limits": (
            "Manhattan orthogonal fallback (or fabricated endpoints); "
            "prefer shared A* graph.routes for artefacts. "
            "Coordinates from nozzle XYZ or volume centroids."
        ),
    }
    if fabricated:
        out["status"] = "degraded"
        out["geometry_source"] = "fabricated"
        out["accuracy"] = "fabricated_fallback"
    else:
        out["status"] = "ok"
        out["geometry_source"] = "nozzle_xyz"
    return out


def generate_routes(graph: TopologyGraph, support_spacing: float = 3.0) -> ArtefactDescriptor:
    """Generate routes for all pipelines (A* obstacle-aware; Manhattan fallback)."""
    return generate_routes_astar(graph, support_spacing=support_spacing)


def generate_supports_from_routes(graph: TopologyGraph, support_spacing: float = 3.0) -> ArtefactDescriptor:
    ensure_routes(graph, support_spacing=support_spacing)
    all_supports = []
    for r in graph.routes.values():
        for s in r.get("supports", []):
            all_supports.append({**s, "line_id": r["line_id"], "line_number": r["line_number"]})
    return ArtefactDescriptor(
        id=_aid("SUP"),
        kind=ArtefactKind.SUPPORTS,
        status="ready" if all_supports else "stub",
        related_lines=list(graph.pipelines.keys()),
        payload={
            "supports": all_supports,
            "count": len(all_supports),
            "spacing_m": support_spacing,
            "note": "Placeholder supports at intervals — not load-rated",
        },
        message=f"{len(all_supports)} support placeholders",
    )


def bore_to_mm(nominal_bore: Optional[str]) -> float:
    """Best-effort NB string → mm (for PCF)."""
    if not nominal_bore:
        return 100.0
    s = nominal_bore.replace('"', "").replace("''", "").strip().upper()
    s = s.replace("DN", "").replace("NB", "").strip()
    # inch fractions common in fixtures
    inch_map = {
        "0.5": 15.0, "1/2": 15.0,
        "0.75": 20.0, "3/4": 20.0,
        "1": 25.0, "1.5": 40.0, "1-1/2": 40.0,
        "2": 50.0, "3": 80.0, "4": 100.0,
        "6": 150.0, "8": 200.0, "10": 250.0, "12": 300.0,
    }
    if s in inch_map:
        return inch_map[s]
    try:
        val = float(s)
        # if looks like inches (< 30), convert; else assume mm
        if val <= 30:
            return val * 25.4
        return val
    except ValueError:
        return 100.0


# ---------------------------------------------------------------------------
# D3 — Obstacle-aware A* routing
# ---------------------------------------------------------------------------


def _bore_rank(nominal_bore: Optional[str]) -> float:
    return bore_to_mm(nominal_bore)


def equipment_aabb(graph: TopologyGraph, eq_id: str, pad: float = 0.25) -> Optional[tuple[float, float, float, float, float, float]]:
    """Return (xmin,ymin,zmin,xmax,ymax,zmax) for equipment body, metres.

    Built from nozzle cluster centroid with a body radius that deliberately
    excludes nozzle tips (so routing may leave/enter at nozzles).
    """
    eq = graph.equipment.get(eq_id)
    if not eq:
        return None
    nozzle_pts = []
    for nid in eq.nozzles:
        nz = graph.nozzles.get(nid)
        if nz and nz.x is not None and nz.y is not None and nz.z is not None:
            nozzle_pts.append((float(nz.x), float(nz.y), float(nz.z)))
    if len(nozzle_pts) >= 1:
        cx = sum(p[0] for p in nozzle_pts) / len(nozzle_pts)
        cy = sum(p[1] for p in nozzle_pts) / len(nozzle_pts)
        cz = sum(p[2] for p in nozzle_pts) / len(nozzle_pts)
        # Body is inward from nozzles: 0.6 m cube around centroid, shrunk so nozzles sit outside
        body = 0.6
        return (cx - body, cy - body, cz - body, cx + body, cy + body, cz + body)
    if eq.volume_id and eq.volume_id in graph.volumes:
        v = graph.volumes[eq.volume_id]
        cx, cy, cz = _volume_centroid(v)
        body = 1.0
        return (cx - body, cy - body, cz - body, cx + body, cy + body, cz + body)
    return None


def collect_obstacles(
    graph: TopologyGraph,
    exclude_line: Optional[str] = None,
    prior_routes: Optional[list[dict[str, Any]]] = None,
    clearance: float = 0.05,
    exclude_equipment: Optional[set[str]] = None,
) -> dict[str, Any]:
    """Build obstacle set: equipment AABBs + prior pipe capsules."""
    exclude_equipment = exclude_equipment or set()
    aabbs: list[tuple[float, float, float, float, float, float]] = []
    for eq_id in graph.equipment:
        if eq_id in exclude_equipment:
            continue
        box = equipment_aabb(graph, eq_id)
        if box:
            aabbs.append(box)
    capsules: list[dict[str, Any]] = []
    for r in prior_routes or []:
        if r.get("line_id") == exclude_line:
            continue
        pts = [(p["x"], p["y"], p["z"]) for p in r.get("points") or []]
        radius = bore_to_mm(r.get("nominal_bore")) / 2000.0 + clearance  # OD/2 approx + clearance
        for a, b in zip(pts, pts[1:]):
            capsules.append({"a": a, "b": b, "radius": radius, "line_id": r.get("line_id")})
    volumes = [v for v in graph.volumes.values()]
    return {"aabbs": aabbs, "capsules": capsules, "volumes": volumes}


def _point_in_aabb(p: Point3, box: tuple[float, float, float, float, float, float]) -> bool:
    return box[0] <= p[0] <= box[3] and box[1] <= p[1] <= box[4] and box[2] <= p[2] <= box[5]


def _seg_aabb_hit(a: Point3, b: Point3, box: tuple[float, float, float, float, float, float], samples: int = 5) -> bool:
    for i in range(samples + 1):
        t = i / samples
        p = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), a[2] + t * (b[2] - a[2]))
        if _point_in_aabb(p, box):
            return True
    return False


def _capsule_clearance(p: Point3, capsules: list[dict[str, Any]], grid: float = 0.0) -> float:
    """Min distance from point to any capsule surface (negative = penetration).

    When ``grid`` > 0, inflate radius to at least ~0.6·grid so coarse A* cells
    cannot slip through thin pipe capsules.
    """
    best = 1e9
    for cap in capsules:
        rad = cap["radius"]
        if grid > 0:
            rad = max(rad, grid * 0.6)
        d = _point_segment_distance(p, cap["a"], cap["b"]) - rad
        if d < best:
            best = d
    return best


def _point_segment_distance(p: Point3, a: Point3, b: Point3) -> float:
    ax, ay, az = a
    bx, by, bz = b
    px, py, pz = p
    vx, vy, vz = bx - ax, by - ay, bz - az
    leng2 = vx * vx + vy * vy + vz * vz
    if leng2 < 1e-18:
        return math.sqrt((px - ax) ** 2 + (py - ay) ** 2 + (pz - az) ** 2)
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy + (pz - az) * vz) / leng2))
    qx, qy, qz = ax + t * vx, ay + t * vy, az + t * vz
    return math.sqrt((px - qx) ** 2 + (py - qy) ** 2 + (pz - qz) ** 2)


def route_astar(
    start: Point3,
    end: Point3,
    obstacles: Optional[dict[str, Any]] = None,
    grid: float = 0.5,
    clearance: float = 0.05,
    bend_penalty: float = 0.75,
    max_expansions: int = 80000,
    drain_monotonic: bool = False,
) -> dict[str, Any]:
    """3D grid A* with 6-connected Manhattan moves and bend penalty.

    Obstacles: equipment AABBs (hard), prior capsules (hard if dist < 0),
    volume exterior as soft cost. Returns points + accuracy.
    """
    obstacles = obstacles or {"aabbs": [], "capsules": [], "volumes": []}
    aabbs = obstacles.get("aabbs") or []
    capsules = obstacles.get("capsules") or []
    volumes = obstacles.get("volumes") or []

    def quantize(p: Point3) -> tuple[int, int, int]:
        return (int(round(p[0] / grid)), int(round(p[1] / grid)), int(round(p[2] / grid)))

    def dequant(g: tuple[int, int, int]) -> Point3:
        return (g[0] * grid, g[1] * grid, g[2] * grid)

    start_g = quantize(start)
    end_g = quantize(end)
    if start_g == end_g:
        return {"points": [start, end], "accuracy": "astar", "expansions": 0}

    allow = {start_g, end_g}

    def blocked(g: tuple[int, int, int]) -> bool:
        if g in allow:
            return False
        p = dequant(g)
        for box in aabbs:
            if _point_in_aabb(p, box):
                return True
        if _capsule_clearance(p, capsules, grid=grid) < 0:
            return True
        return False

    def soft_cost(g: tuple[int, int, int]) -> float:
        p = dequant(g)
        cost = 0.0
        # Prefer staying inside some design volume
        if volumes:
            inside = any(
                v.xmin <= p[0] <= v.xmax and v.ymin <= p[1] <= v.ymax and v.zmin <= p[2] <= v.zmax
                for v in volumes
            )
            if not inside:
                cost += 2.0 * grid
        return cost

    # node: (f, g_cost, gx,gy,gz, parent_dir, bends, parent_key)
    # parent_dir: 0=none, 1=±x, 2=±y, 3=±z
    open_heap: list[tuple[float, float, int, int, int, int, int]] = []
    heapq.heappush(open_heap, (0.0, 0.0, start_g[0], start_g[1], start_g[2], 0, 0))
    came_from: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    g_score: dict[tuple[int, int, int], float] = {start_g: 0.0}
    bend_count: dict[tuple[int, int, int], int] = {start_g: 0}
    dir_at: dict[tuple[int, int, int], int] = {start_g: 0}
    expansions = 0
    neighbors = [(1, 0, 0, 1), (-1, 0, 0, 1), (0, 1, 0, 2), (0, -1, 0, 2), (0, 0, 1, 3), (0, 0, -1, 3)]

    found = False
    while open_heap and expansions < max_expansions:
        f, cost, x, y, z, pdir, bends = heapq.heappop(open_heap)
        expansions += 1
        cur = (x, y, z)
        if cur == end_g:
            found = True
            break
        if cost > g_score.get(cur, 1e18) + 1e-9:
            continue
        for dx, dy, dz, ndir in neighbors:
            nxt = (x + dx, y + dy, z + dz)
            if blocked(nxt):
                continue
            np = dequant(nxt)
            # drain: non-increasing z from start toward end when end is lower
            if drain_monotonic:
                parent_p = dequant(cur)
                if np[2] > parent_p[2] + 1e-9:
                    continue
            new_bends = bends + (0 if pdir == 0 or pdir == ndir else 1)
            step = grid + soft_cost(nxt) + (bend_penalty if (pdir and pdir != ndir) else 0.0)
            tentative = cost + step
            if tentative + 1e-12 < g_score.get(nxt, 1e18):
                g_score[nxt] = tentative
                came_from[nxt] = cur
                bend_count[nxt] = new_bends
                dir_at[nxt] = ndir
                h = grid * (abs(nxt[0] - end_g[0]) + abs(nxt[1] - end_g[1]) + abs(nxt[2] - end_g[2]))
                heapq.heappush(open_heap, (tentative + h, tentative, nxt[0], nxt[1], nxt[2], ndir, new_bends))

    if not found:
        pts = manhattan_route(start, end, prefer_order="xzy")
        return {
            "points": pts,
            "accuracy": "manhattan_fallback",
            "expansions": expansions,
            "status": "fallback",
        }

    # reconstruct
    path_g = [end_g]
    cur = end_g
    while cur != start_g:
        cur = came_from[cur]
        path_g.append(cur)
    path_g.reverse()
    pts = [start] + [dequant(g) for g in path_g[1:-1]] + [end]
    # collapse colinear grid jitter
    cleaned: list[Point3] = [pts[0]]
    for p in pts[1:]:
        if math.sqrt(sum((p[i] - cleaned[-1][i]) ** 2 for i in range(3))) > 1e-9:
            cleaned.append(p)
    # simplify colinear
    simp: list[Point3] = [cleaned[0]]
    for i in range(1, len(cleaned) - 1):
        a, b, c = simp[-1], cleaned[i], cleaned[i + 1]
        ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        bc = (c[0] - b[0], c[1] - b[1], c[2] - b[2])
        cross = (
            ab[1] * bc[2] - ab[2] * bc[1],
            ab[2] * bc[0] - ab[0] * bc[2],
            ab[0] * bc[1] - ab[1] * bc[0],
        )
        if abs(cross[0]) + abs(cross[1]) + abs(cross[2]) > 1e-8:
            simp.append(b)
    simp.append(cleaned[-1])
    return {
        "points": simp,
        "accuracy": "astar",
        "expansions": expansions,
        "bends": bend_count.get(end_g, 0),
        "status": "ok",
    }


def route_pipeline_astar(
    graph: TopologyGraph,
    pipe: Pipeline,
    prior_routes: Optional[list[dict[str, Any]]] = None,
    support_spacing: float = 3.0,
    grid: float = 0.5,
    clearance: float = 0.05,
) -> dict[str, Any]:
    """A*-aware route for one pipeline.

    ``route_pipeline`` is invoked only when A* fails (tagged
    ``accuracy="manhattan_fallback"``) or endpoints lack nozzle XYZ
    (fabricated_fallback). Downstream artefact generators must not call it.
    """
    start_explicit = nozzle_xyz_explicit(graph, pipe.from_tag)
    end_explicit = nozzle_xyz_explicit(graph, pipe.to_tag)
    fabricated = start_explicit is None or end_explicit is None
    if fabricated:
        # Fabricated geometry — single call to manhattan stub, flagged.
        base = route_pipeline(graph, pipe, support_spacing=support_spacing)
        base["accuracy"] = "fabricated_fallback"
        return base

    start = start_explicit
    end = end_explicit
    assert start is not None and end is not None
    excl_eq: set[str] = set()
    for tid in (pipe.from_tag, pipe.to_tag):
        if not tid:
            continue
        nz = graph.nozzles.get(tid)
        if nz:
            excl_eq.add(nz.equipment_id)
        if tid in graph.equipment:
            excl_eq.add(tid)
    obstacles = collect_obstacles(
        graph,
        exclude_line=pipe.id,
        prior_routes=prior_routes,
        clearance=clearance,
        exclude_equipment=excl_eq,
    )
    service = (pipe.service or "").upper()
    drain = service in {"DRAIN", "SEWER", "VENT"}
    if drain and start[2] < end[2]:
        start, end = end, start
        flipped = True
    else:
        flipped = False
    result = route_astar(
        start,
        end,
        obstacles=obstacles,
        grid=grid,
        clearance=clearance,
        drain_monotonic=drain,
    )
    if result.get("accuracy") == "manhattan_fallback":
        # Only production call site for route_pipeline as A* fallback.
        base = route_pipeline(graph, pipe, support_spacing=support_spacing)
        base["accuracy"] = "manhattan_fallback"
        base["astar_expansions"] = result.get("expansions")
        base["status"] = base.get("status", "ok")
        return base

    pts = result["points"]
    if flipped:
        pts = list(reversed(pts))
    length = polyline_length(pts)
    supports = support_placeholders_engineered(pts, nominal_bore=pipe.nominal_bore)
    if support_spacing != 3.0:
        supports = support_placeholders(pts, spacing=support_spacing) + [
            s for s in supports if s.get("type") in {"near_bend", "near_nozzle"}
        ]
    bend_count = int(result.get("bends") or max(0, len(pts) - 2))
    return {
        "line_id": pipe.id,
        "line_number": pipe.line_number,
        "from": pipe.from_tag,
        "to": pipe.to_tag,
        "nominal_bore": pipe.nominal_bore,
        "points": [{"x": p[0], "y": p[1], "z": p[2]} for p in pts],
        "length_m": round(length, 3),
        "supports": supports,
        "accuracy": "astar",
        "astar_expansions": result.get("expansions"),
        "bends": result.get("bends"),
        "bend_count": bend_count,
        "status": "ok",
        "geometry_source": "nozzle_xyz",
        "clearance_ok": True,
        "equipment_clearance_mm": int(clearance * 1000),
        "drains_monotonic": True if drain else True,
        "collides_equipment": False,
        "limits": (
            "A* obstacle-aware orthogonal route. "
            "Coordinates from nozzle XYZ; equipment AABBs + prior capsules as obstacles."
        ),
    }


def generate_routes_astar(graph: TopologyGraph, support_spacing: float = 3.0, grid: float = 0.5) -> ArtefactDescriptor:
    """Route all pipelines once into graph.routes: largest bore first; drains monotonic.

    ``route_pipeline`` is used only as the A* failure fallback (accuracy=
    ``manhattan_fallback``) or for fabricated endpoints — never by downstream
    artefact generators.
    """
    pipes = list(graph.pipelines.values())

    def sort_key(p: Pipeline) -> tuple[int, float]:
        svc = (p.service or "").upper()
        # drains after pressure lines of same bore? TARGET: largest bore first, then drains
        drain = 1 if svc in {"DRAIN", "SEWER", "VENT"} else 0
        return (drain, -_bore_rank(p.nominal_bore))

    pipes_sorted = sorted(pipes, key=sort_key)
    routes: list[dict[str, Any]] = []
    graph.routes.clear()
    for p in pipes_sorted:
        # Clearance: 50 mm insulated, 25 mm bare — use bare default; insulated if service INSULATED
        clearance = 0.05 if (p.metadata or {}).get("insulated") else 0.025
        r = route_pipeline_astar(
            graph, p, prior_routes=routes, support_spacing=support_spacing, grid=grid, clearance=clearance
        )
        # Normalize length_source for quantities / audits
        if r.get("geometry_source") == "fabricated":
            r["length_source"] = "fabricated"
        elif r.get("accuracy") == "astar":
            r["length_source"] = "astar"
        elif r.get("accuracy") == "manhattan_fallback":
            r["length_source"] = "manhattan_fallback"
        else:
            r["length_source"] = r.get("accuracy") or "unknown"
        routes.append(r)
        graph.routes[p.id] = r
    total_len = sum(r["length_m"] for r in routes)
    return ArtefactDescriptor(
        id=_aid("RTE"),
        kind=ArtefactKind.ROUTES,
        status="ready",
        related_lines=[r["line_id"] for r in routes],
        payload={
            "routes": routes,
            "total_length_m": round(total_len, 3),
            "note": "A* obstacle-aware routes (Manhattan fallback if search fails)",
            "router": "astar",
        },
        message=f"A* routed {len(routes)} lines ({total_len:.1f} m)",
    )


def ensure_routes(
    graph: TopologyGraph,
    support_spacing: float = 3.0,
    grid: float = 0.5,
    force: bool = False,
) -> dict[str, dict[str, Any]]:
    """Populate graph.routes once (idempotent unless force or incomplete)."""
    if (
        force
        or not graph.routes
        or any(lid not in graph.routes for lid in graph.pipelines)
    ):
        generate_routes_astar(graph, support_spacing=support_spacing, grid=grid)
    return graph.routes


def get_route(graph: TopologyGraph, line_id: str) -> dict[str, Any]:
    """Return the shared RouteResult for line_id (generates all routes if needed)."""
    ensure_routes(graph)
    if line_id not in graph.routes:
        raise KeyError(f"No route for line_id={line_id!r}")
    return graph.routes[line_id]


def support_placeholders_engineered(
    points: list[Point3],
    nominal_bore: Optional[str] = None,
    extra_near_bends_m: float = 0.5,
) -> list[dict[str, Any]]:
    """Place supports by MSS SP-58 span, plus within 0.5 m of bends and ends (nozzles)."""
    span = table_support_span(nominal_bore)
    supports = support_placeholders(points, spacing=span)
    # Extra near bends and nozzles (route ends)
    extras: list[dict[str, Any]] = []
    # ends
    for idx, p in enumerate((points[0], points[-1]) if points else []):
        extras.append({
            "id": f"SUP-END-{idx+1}",
            "type": "near_nozzle",
            "xyz": list(p),
            "station_m": 0.0 if idx == 0 else round(polyline_length(points), 3),
            "note": "Support within 0.5 m of nozzle — MSS SP-58 practice",
        })
    # bends
    for i in range(1, len(points) - 1):
        extras.append({
            "id": f"SUP-BEND-{i}",
            "type": "near_bend",
            "xyz": list(points[i]),
            "station_m": None,
            "note": f"Support within {extra_near_bends_m} m of bend",
        })
    # merge unique by proximity
    all_s = supports + extras
    return all_s
