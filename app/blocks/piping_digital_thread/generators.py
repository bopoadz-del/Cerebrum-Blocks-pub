# Ported (real) from <private-repo> src/<private-repo>/generators.py (donor HEAD on disk).
# Intra-package imports are rewritten to relative imports; the code is
# otherwise carried verbatim. DEXPI ingestion is NOT duplicated here: the
# Store's dexpi_ingest block (ported from ingest_dexpi.py) covers ingestion,
# and this package carries the downstream digital thread (graph, routing,
# tables, clash, schedule 4D, generators, PCF, maturity, cascade, exporters).
# The agent/API layers (agent_tools, cli, server, mcp_server) are not ported.
"""Generators: quantities, isos, PCF text, GA SVG, systems, test packs, CWP/IWP, routes."""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path
from typing import Any, Optional

from .clash import generate_clash_report
from .graph import TopologyGraph
from .models import (
    ArtefactDescriptor,
    ArtefactKind,
    Discipline,
    TestPack,
    WorkPackage,
    WPType,
)
from .routing import (
    bore_to_mm,
    ensure_routes,
    generate_routes,
    generate_supports_from_routes,
    get_route,
)
from .tables import (
    flange_bolts,
    flange_thickness_m,
    gasket_thickness_m,
    hydrotest_pressure_barg,
    mass_per_m,
    next_smaller_bore,
    od_mm,
    reducer_face_to_face_m,
    valve_face_to_face_m,
)


def _aid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def default_output_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "output"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Quantities
# ---------------------------------------------------------------------------

def generate_quantities(
    graph: TopologyGraph,
    line_ids: Optional[list[str]] = None,
    output_dir: Optional[Path] = None,
) -> ArtefactDescriptor:
    """Build a quantities take-off (counts real; lengths from shared A* routes)."""
    ensure_routes(graph)
    pipes = list(graph.pipelines.values())
    if line_ids:
        pipes = [p for p in pipes if p.id in line_ids]
    rows = []
    for p in pipes:
        route = get_route(graph, p.id)
        length_source = route.get("length_source") or (
            "fabricated"
            if route.get("geometry_source") == "fabricated"
            else route.get("accuracy") or "astar"
        )
        schedule = (p.metadata or {}).get("schedule") or "40"
        kg_m = mass_per_m(p.nominal_bore, schedule)
        weight_kg = round(kg_m * float(route["length_m"]), 3)
        # bolts/gaskets per flange pair
        n_flange = sum(
            1
            for cid in p.component_tags
            if (graph.tags.get(cid) and (graph.tags[cid].engineering.component_class or "").upper().startswith("FLANGE"))
            or "FLG" in cid.upper()
            or "FLANGE" in cid.upper()
        )
        bolt_count, bolt_dia = flange_bolts(p.nominal_bore, 150)
        pairs = max(n_flange // 2, n_flange)  # each flange implies a joint
        od = od_mm(p.nominal_bore) / 1000.0
        surface_m2 = round(math.pi * od * float(route["length_m"]), 3)
        insulation_mm = None
        for key in ("insulation_mm", "InsulationThickness", "InsulationThicknessAssignmentClass"):
            raw = (p.metadata or {}).get(key)
            if raw not in (None, ""):
                try:
                    insulation_mm = float(raw)
                    break
                except (TypeError, ValueError):
                    continue
        # Outer surface over insulation when present
        if insulation_mm and insulation_mm > 0:
            od_ins = od + 2.0 * (insulation_mm / 1000.0)
            insulation_m2 = round(math.pi * od_ins * float(route["length_m"]), 3)
        else:
            insulation_m2 = 0.0
        # PCF component count reconciliation (best-effort from fittings on route)
        fittings = route.get("fittings") or []
        pcf_component_count = int(route.get("pcf_component_count") or (len(fittings) + max(len(route.get("points") or []) - 1, 0)))
        rows.append(
            {
                "line_id": p.id,
                "line_number": p.line_number,
                "nominal_bore": p.nominal_bore,
                "service": p.service,
                "component_count": len(p.component_tags),
                "pcf_component_count": pcf_component_count,
                "length_m": route["length_m"],
                "length_source": length_source,
                "geometry_source": route.get("geometry_source", "unknown"),
                "weight_kg": weight_kg,
                "mass_kg_per_m": round(kg_m, 3),
                "bolts": pairs * bolt_count,
                "bolt_dia_in": bolt_dia,
                "gaskets": pairs,
                "surface_m2": surface_m2,
                "insulation_mm": insulation_mm,
                "insulation_m2": insulation_m2,
                "status": "degraded" if route.get("status") == "degraded" else "ready",
            }
        )
    out: Optional[Path] = None
    if output_dir is not None:
        out = _ensure_dir(Path(output_dir) / "qty") / "quantities.json"
        out.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    return ArtefactDescriptor(
        id=_aid("QTY"),
        kind=ArtefactKind.QUANTITIES,
        status="ready" if rows else "stub",
        path=str(out) if out else None,
        related_lines=[p.id for p in pipes],
        related_tags=[t for p in pipes for t in p.component_tags],
        payload={"rows": rows, "note": "Lengths from shared A* graph.routes (not surveyed)"},
        message="Quantities with shared A* lengths",
    )


# ---------------------------------------------------------------------------
# Isometric package (JSON + SVG sketch)
# ---------------------------------------------------------------------------

def _iso_svg(route: dict[str, Any], line_number: str, bom: Optional[list[dict[str, Any]]] = None) -> str:
    """True isometric projection SVG (x@30°, y@150°, z vertical) with dimensions + BOM.

    Not a certified ISOGEN drawing — title block states HEURISTIC — NOT FOR CONSTRUCTION.
    """
    pts = route.get("points") or []
    if not pts:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">'
            '<text x="20" y="40">no route</text></svg>'
        )

    def project(pt: dict[str, Any]) -> tuple[float, float]:
        x, y, z = float(pt["x"]), float(pt["y"]), float(pt["z"])
        return (
            (x - y) * math.cos(math.radians(30)),
            (x + y) * math.sin(math.radians(30)) + z,
        )

    proj = [project(pt) for pt in pts]
    xs = [pt[0] for pt in proj]
    ys = [pt[1] for pt in proj]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    pad = 60
    w, h = 900, 640
    span_x = max(maxx - minx, 1e-3)
    span_y = max(maxy - miny, 1e-3)

    def sx(x: float) -> float:
        return pad + (x - minx) / span_x * (w - 2 * pad - 200)

    def sy(y: float) -> float:
        return h - pad - 80 - (y - miny) / span_y * (h - 2 * pad - 100)

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        '<rect width="100%" height="100%" fill="#0f1419"/>',
        f'<text x="{pad}" y="28" fill="#9ad1ff" font-family="monospace" font-size="16">'
        f"ISO {line_number}</text>",
        f'<text x="{pad}" y="48" fill="#fbbf24" font-family="monospace" font-size="11">'
        f"HEURISTIC — NOT FOR CONSTRUCTION</text>",
    ]
    parts.append(
        f'<g transform="translate({w - 80},{70})">'
        f'<line x1="0" y1="20" x2="0" y2="-20" stroke="#e2e8f0" stroke-width="2"/>'
        f'<polygon points="0,-28 -6,-12 6,-12" fill="#e2e8f0"/>'
        f'<text x="8" y="-18" fill="#e2e8f0" font-size="12" font-family="monospace">N north</text></g><!-- north-arrow -->'
    )
    dim_sum_mm = 0
    if len(proj) >= 2:
        d = " ".join(
            f"{'M' if i == 0 else 'L'} {sx(pt[0]):.1f} {sy(pt[1]):.1f}" for i, pt in enumerate(proj)
        )
        parts.append(f'<path d="{d}" fill="none" stroke="#5eead4" stroke-width="3"/>')
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            ax, ay, az = float(a["x"]), float(a["y"]), float(a["z"])
            bx, by, bz = float(b["x"]), float(b["y"]), float(b["z"])
            leng_m = math.sqrt((bx - ax) ** 2 + (by - ay) ** 2 + (bz - az) ** 2)
            leng_mm = int(round(leng_m * 1000))
            dim_sum_mm += leng_mm
            mid = project({"x": (ax + bx) / 2, "y": (ay + by) / 2, "z": (az + bz) / 2})
            parts.append(
                f'<text x="{sx(mid[0]):.1f}" y="{sy(mid[1]) - 8:.1f}" fill="#fca5a5" '
                f'font-family="monospace" font-size="10" text-anchor="middle">{leng_mm}</text>'
            )
            if leng_m > 12:
                parts.append(
                    f'<circle cx="{sx(mid[0]):.1f}" cy="{sy(mid[1]):.1f}" r="3" fill="#f472b6"/>'
                )
    for pt in proj:
        parts.append(f'<circle cx="{sx(pt[0]):.1f}" cy="{sy(pt[1]):.1f}" r="4" fill="#fbbf24"/>')
    bom_list = bom or []
    bx0, by0 = w - 190, 100
    parts.append(
        f'<rect x="{bx0 - 10}" y="{by0 - 20}" width="180" height="{30 + 14 * max(len(bom_list), 1)}" '
        f'fill="#1e293b" stroke="#475569"/>'
    )
    parts.append(
        f'<text x="{bx0}" y="{by0}" fill="#e2e8f0" font-family="monospace" font-size="11">BOM</text>'
    )
    for i, item in enumerate(bom_list[:12]):
        parts.append(
            f'<text x="{bx0}" y="{by0 + 16 + i * 14}" fill="#94a3b8" font-family="monospace" font-size="10">'
            f'{str(item.get("tag", "?"))[:18]} {str(item.get("type", ""))[:8]}</text>'
        )
    parts.append(
        f'<rect x="{pad}" y="{h - 70}" width="{w - 2 * pad}" height="55" fill="#1e293b" stroke="#334155"/>'
    )
    frm = route.get("from") or "?"
    to = route.get("to") or "?"
    parts.append(
        f'<text x="{pad + 8}" y="{h - 45}" fill="#e2e8f0" font-family="monospace" font-size="11">'
        f"Line {line_number} | {frm} → {to} | L={route.get('length_m', 0)} m | "
        f"dim_sum_mm={dim_sum_mm} | sheet 1/1</text>"
    )
    parts.append(
        f'<text x="{pad + 8}" y="{h - 25}" fill="#64748b" font-family="monospace" font-size="10">'
        f"HEURISTIC — NOT FOR CONSTRUCTION</text>"
    )
    parts.append(f"<!-- dim_sum_mm={dim_sum_mm} -->")
    parts.append("</svg>")
    return "\n".join(parts)



def generate_isometric(
    graph: TopologyGraph,
    line_id: str,
    output_dir: Optional[Path] = None,
) -> ArtefactDescriptor:
    """Generate isometric package: JSON descriptor + SVG line sketch."""
    pipe = graph.pipelines.get(line_id)
    if pipe is None:
        return ArtefactDescriptor(
            id=_aid("ISO"),
            kind=ArtefactKind.ISOMETRIC,
            status="failed",
            related_lines=[line_id],
            message=f"Line not found: {line_id}",
        )
    route = get_route(graph, line_id)
    fabricated = route.get("geometry_source") == "fabricated"
    package = {
        "line_number": pipe.line_number,
        "line_id": pipe.id,
        "from": pipe.from_tag,
        "to": pipe.to_tag,
        "nominal_bore": pipe.nominal_bore,
        "service": pipe.service,
        "material": pipe.material,
        "components": pipe.component_tags,
        "bom": [
            {
                "tag": cid,
                "type": (graph.tags[cid].engineering.component_class if cid in graph.tags else "UNK"),
            }
            for cid in pipe.component_tags
        ],
        "route": route,
        "drawing_format": "iso-package-v1",
        "projection": "30deg",
        "iso_angle_deg": 30,
        "angle_deg": 30,
        "geometry_source": route.get("geometry_source", "unknown"),
        "status": "degraded" if fabricated else "ready",
        "note": "Structured iso package — not a certified ISOGEN drawing",
    }
    title = pipe.line_number + (" [FABRICATED GEOMETRY]" if fabricated else "")
    svg = _iso_svg(route, title, bom=package.get("bom"))
    paths: dict[str, str] = {}
    if output_dir is not None:
        iso_dir = _ensure_dir(Path(output_dir) / "iso")
        safe = pipe.line_number.replace("/", "_").replace(" ", "_")
        json_path = iso_dir / f"{safe}.iso.json"
        svg_path = iso_dir / f"{safe}.iso.svg"
        json_path.write_text(json.dumps(package, indent=2), encoding="utf-8")
        svg_path.write_text(svg, encoding="utf-8")
        paths = {"json": str(json_path), "svg": str(svg_path)}
        package["files"] = paths

    return ArtefactDescriptor(
        id=_aid("ISO"),
        kind=ArtefactKind.ISOMETRIC,
        status="ready",
        path=paths.get("json") or f"artefacts/iso/{pipe.line_number}.iso.json",
        related_lines=[line_id],
        related_tags=list(pipe.component_tags),
        payload=package,
        message="Isometric package (JSON + SVG sketch) written" if paths else "Isometric package ready",
    )


# ---------------------------------------------------------------------------
# PCF text writer — sequential contiguous components (validity target, not cert)
# ---------------------------------------------------------------------------

# Public structural SKEY map (ISOGEN-style mnemonics documented in open parsers;
# not a redistributed Autodesk catalogue).
_CLASS_TO_SKEY = {
    "FLANGE": "FLWN",
    "BLIND": "FLBL",
    "BLINDFLANGE": "FLBL",
    "GASKET": "GASK",
    "VALVE": "VBAL",
    "VALVE-BALL": "VBAL",
    "VALVE-GATE": "VGAT",
    "VALVE-ISOLATION": "VGAT",
    "REDUCER": "RCON",
    "TEE": "TEBW",
    "ELBOW": "ELBW",
    "PIPE": "PIPE",
    "SUPPORT": "SUPPORT",
}


def _pcf_coord(x: float, y: float, z: float) -> str:
    """Metres → integer millimetres."""
    return f"{int(round(x * 1000))} {int(round(y * 1000))} {int(round(z * 1000))}"


def _unit(vx: float, vy: float, vz: float) -> tuple[float, float, float]:
    import math

    n = math.sqrt(vx * vx + vy * vy + vz * vz)
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    return (vx / n, vy / n, vz / n)


def _is_bend(prev: tuple[float, float, float], cur: tuple[float, float, float], nxt: tuple[float, float, float]) -> bool:
    d1 = (abs(cur[0] - prev[0]) > 1e-9, abs(cur[1] - prev[1]) > 1e-9, abs(cur[2] - prev[2]) > 1e-9)
    d2 = (abs(nxt[0] - cur[0]) > 1e-9, abs(nxt[1] - cur[1]) > 1e-9, abs(nxt[2] - cur[2]) > 1e-9)
    return d1 != d2


def _long_radius_m(nominal_bore: Optional[str]) -> float:
    """Long-radius elbow R = 1.5 × NPS (NPS in inches → metres).

    Citation: ASME B16.9 long-radius elbow centreline radius = 1.5 × NPS.
    """
    bore_mm = bore_to_mm(nominal_bore)
    nps_in = bore_mm / 25.4
    return 1.5 * nps_in * 0.0254


def _skey_for_tag(graph: TopologyGraph, tag_id: str) -> tuple[str, str]:
    """Return (component_kind, skey) for a component tag."""
    tag = graph.tags.get(tag_id)
    ctype = (tag.engineering.component_class if tag else None) or "COMP"
    ctype_u = ctype.upper().replace(" ", "").replace("_", "-")
    # subtype hints
    name_u = (tag.name if tag else tag_id).upper()
    if "GATE" in name_u or ctype_u in ("VALVE-GATE", "VALVE-ISOLATION"):
        return "VALVE", "VGAT"
    if "BALL" in name_u or ctype_u == "VALVE-BALL":
        return "VALVE", "VBAL"
    if "BLIND" in name_u or "BLIND" in ctype_u:
        return "FLANGE", "FLBL"
    kind = ctype_u.split("-")[0]
    if kind in ("FLANGE", "GASKET", "VALVE", "REDUCER", "TEE", "ELBOW", "PIPE", "SUPPORT"):
        return kind, _CLASS_TO_SKEY.get(ctype_u, _CLASS_TO_SKEY.get(kind, "PIPE"))
    return "PIPE", _CLASS_TO_SKEY.get(ctype_u, "PIPE")


def _route_length(pts: list[tuple[float, float, float]]) -> float:
    import math

    total = 0.0
    for a, b in zip(pts, pts[1:]):
        total += math.sqrt(sum((b[i] - a[i]) ** 2 for i in range(3)))
    return total


def _point_at_station(pts: list[tuple[float, float, float]], station_m: float) -> tuple[float, float, float]:
    import math

    if not pts:
        return (0.0, 0.0, 0.0)
    if len(pts) == 1 or station_m <= 0:
        return pts[0]
    acc = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = math.sqrt(sum((b[i] - a[i]) ** 2 for i in range(3)))
        if seg < 1e-12:
            continue
        if acc + seg >= station_m:
            t = (station_m - acc) / seg
            return tuple(a[i] + t * (b[i] - a[i]) for i in range(3))  # type: ignore[return-value]
        acc += seg
    return pts[-1]


def write_pcf_text(graph: TopologyGraph, line_id: str) -> str:
    """Emit a structurally valid sequential PCF for a pipeline.

    Walks the route; at each bend inserts a long-radius ELBOW whose END-POINTs
    are the tangent points (R = 1.5·NPS). PIPE segments stop at those tangents
    so components are contiguous (no pipe/elbow overlap). Fittings from
    component_tags are inserted into the chain at station (explicit or inferred).

    Certification / full ISOGEN catalogue remain a WALL — this targets validity.
    """
    import math
    from typing import Any as _Any

    pipe = graph.pipelines[line_id]
    route = get_route(graph, line_id)
    pts = [(float(p["x"]), float(p["y"]), float(p["z"])) for p in route["points"]]
    fabricated = (
        route.get("geometry_source") == "fabricated"
        or route.get("status") == "degraded"
        or len(pts) < 2
    )
    if len(pts) < 2:
        pts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
        fabricated = True

    bore_mm = bore_to_mm(pipe.nominal_bore)
    bore_str = f"{bore_mm:.1f}"
    spec = (pipe.metadata or {}).get("spec") or pipe.material or "UNSPEC"
    R = _long_radius_m(pipe.nominal_bore)

    # --- build geometric spine as list of dict events ---
    spine: list[dict[str, _Any]] = []
    current = pts[0]
    for i in range(len(pts) - 1):
        a = pts[i]
        b = pts[i + 1]
        has_bend = i + 1 < len(pts) - 1 and _is_bend(pts[i], pts[i + 1], pts[i + 2])
        if has_bend:
            nxt = pts[i + 2]
            u_in = _unit(b[0] - a[0], b[1] - a[1], b[2] - a[2])
            u_out = _unit(nxt[0] - b[0], nxt[1] - b[1], nxt[2] - b[2])
            leg_in = math.sqrt(sum((b[j] - a[j]) ** 2 for j in range(3)))
            leg_out = math.sqrt(sum((nxt[j] - b[j]) ** 2 for j in range(3)))
            r_use = min(R, 0.45 * leg_in, 0.45 * leg_out)
            if r_use < 1e-6:
                if math.sqrt(sum((b[j] - current[j]) ** 2 for j in range(3))) > 1e-9:
                    spine.append({"kind": "PIPE", "a": current, "b": b})
                current = b
                continue
            tan_in = (b[0] - u_in[0] * r_use, b[1] - u_in[1] * r_use, b[2] - u_in[2] * r_use)
            tan_out = (b[0] + u_out[0] * r_use, b[1] + u_out[1] * r_use, b[2] + u_out[2] * r_use)
            if math.sqrt(sum((tan_in[j] - current[j]) ** 2 for j in range(3))) > 1e-9:
                spine.append({"kind": "PIPE", "a": current, "b": tan_in})
            spine.append(
                {
                    "kind": "ELBOW",
                    "a": tan_in,
                    "b": tan_out,
                    "centre": b,
                    "skey": "ELBW",
                    "angle": 9000,
                    "r": r_use,
                }
            )
            current = tan_out
        else:
            if math.sqrt(sum((b[j] - current[j]) ** 2 for j in range(3))) > 1e-9:
                spine.append({"kind": "PIPE", "a": current, "b": b})
            current = b

    # --- fittings to insert by station along original route (non-zero B16 lengths) ---
    placeable: list[tuple[str, str, str, float, str]] = []
    route_len = _route_length(pts) or 1.0
    candidates = []
    for cid in pipe.component_tags:
        kind, skey = _skey_for_tag(graph, cid)
        if kind in ("PIPE", "ELBOW"):
            continue
        candidates.append((cid, kind, skey))
    for idx, (cid, kind, skey) in enumerate(candidates):
        tag = graph.tags.get(cid)
        if tag and tag.engineering.station_m is not None:
            station = float(tag.engineering.station_m)
            placement = "explicit"
        else:
            station = route_len * (idx + 1) / (len(candidates) + 1)
            placement = "inferred"
        placeable.append((cid, kind, skey, station, placement))
    placeable.sort(key=lambda x: x[3])

    # Expand GASKET into FLANGE–GASKET–FLANGE; consume one FLANGE tag per gasket up front
    expanded: list[dict[str, _Any]] = []
    gasket_count = sum(1 for _, kind, *_ in placeable if kind == "GASKET")
    flange_ids_ordered = [cid for cid, kind, *_ in placeable if kind == "FLANGE"]
    consumed_flanges: set[str] = set(flange_ids_ordered[:gasket_count])
    gasket_mates: list[Optional[str]] = list(flange_ids_ordered[:gasket_count])
    # pad mates if fewer flanges than gaskets
    while len(gasket_mates) < gasket_count:
        gasket_mates.append(None)
    gasket_i = 0
    for cid, kind, skey, station, placement in placeable:
        if kind == "FLANGE" and cid in consumed_flanges:
            continue
        if kind == "GASKET":
            mate = gasket_mates[gasket_i] if gasket_i < len(gasket_mates) else None
            gasket_i += 1
            fl_skey = "FLWN"
            expanded.append(
                {
                    "cid": mate or f"{cid}-FLGA",
                    "kind": "FLANGE",
                    "skey": fl_skey,
                    "station": station,
                    "placement": placement,
                    "length_m": flange_thickness_m(pipe.nominal_bore),
                }
            )
            expanded.append(
                {
                    "cid": cid,
                    "kind": "GASKET",
                    "skey": "GASK",
                    "station": station,
                    "placement": placement,
                    "length_m": gasket_thickness_m(),
                }
            )
            expanded.append(
                {
                    "cid": f"{cid}-FLGB",
                    "kind": "FLANGE",
                    "skey": fl_skey,
                    "station": station,
                    "placement": placement,
                    "length_m": flange_thickness_m(pipe.nominal_bore),
                }
            )
            continue
        if kind == "FLANGE":
            # Lone flange tag → FLANGE–GASKET–FLANGE joint (B16.5 tf + practice gasket)
            fl_len = flange_thickness_m(pipe.nominal_bore)
            expanded.append(
                {
                    "cid": cid,
                    "kind": "FLANGE",
                    "skey": skey or "FLWN",
                    "station": station,
                    "placement": placement,
                    "length_m": fl_len,
                }
            )
            expanded.append(
                {
                    "cid": f"{cid}-GSK",
                    "kind": "GASKET",
                    "skey": "GASK",
                    "station": station,
                    "placement": placement,
                    "length_m": gasket_thickness_m(),
                }
            )
            expanded.append(
                {
                    "cid": f"{cid}-FLGB",
                    "kind": "FLANGE",
                    "skey": skey or "FLWN",
                    "station": station,
                    "placement": placement,
                    "length_m": fl_len,
                }
            )
            continue
        elif kind == "REDUCER":
            bore_out = next_smaller_bore(pipe.nominal_bore)
            length = reducer_face_to_face_m(pipe.nominal_bore, bore_out)
        elif kind == "VALVE":
            length = valve_face_to_face_m(pipe.nominal_bore)
            bore_out = None
        elif kind == "TEE":
            length = max(flange_thickness_m(pipe.nominal_bore) * 2.0, 0.05)
            bore_out = None
        else:
            length = max(0.02, flange_thickness_m(pipe.nominal_bore))
            bore_out = None
        item = {
            "cid": cid,
            "kind": kind,
            "skey": skey,
            "station": station,
            "placement": placement,
            "length_m": length,
        }
        if bore_out is not None:
            item["bore_out"] = bore_out
        expanded.append(item)

    def _seg_len(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
        return math.sqrt(sum((b[j] - a[j]) ** 2 for j in range(3)))

    def _insert_fitting_group(
        chain: list[dict[str, _Any]],
        pos: tuple[float, float, float],
        parts: list[dict[str, _Any]],
    ) -> list[dict[str, _Any]]:
        """Insert one or more contiguous fittings (e.g. FLANGE–GASKET–FLANGE) with length."""
        total_len = sum(float(p["length_m"]) for p in parts)
        span_needed = max(total_len, 1e-4)
        out: list[dict[str, _Any]] = []
        inserted = False
        for seg in chain:
            if inserted or seg["kind"] != "PIPE":
                out.append(seg)
                continue
            a, b = seg["a"], seg["b"]
            ab = _seg_len(a, b)
            if ab < 1e-9:
                out.append(seg)
                continue
            ax, ay, az = a
            bx, by, bz = b
            px, py, pz = pos
            vx, vy, vz = bx - ax, by - ay, bz - az
            t = ((px - ax) * vx + (py - ay) * vy + (pz - az) * vz) / (ab * ab)
            closest = (ax + t * vx, ay + t * vy, az + t * vz)
            dist = _seg_len(pos, closest)
            if 0.0 <= t <= 1.0 and dist < 0.15:
                span = min(span_needed, max(ab * 0.8, 1e-4))
                start_t = max(0.0, min(1.0, t - (span / 2) / ab))
                # scale part lengths into available span
                scale = span / span_needed
                cursor_t = start_t
                fa0 = (ax + start_t * vx, ay + start_t * vy, az + start_t * vz)
                if _seg_len(a, fa0) > 1e-6:
                    out.append({"kind": "PIPE", "a": a, "b": fa0})
                for part in parts:
                    plen = float(part["length_m"]) * scale
                    end_t = min(1.0, cursor_t + plen / ab)
                    fa = (ax + cursor_t * vx, ay + cursor_t * vy, az + cursor_t * vz)
                    fb = (ax + end_t * vx, ay + end_t * vy, az + end_t * vz)
                    meta = {
                        "kind": part["kind"],
                        "skey": part["skey"],
                        "tag": part["cid"],
                        "item_code": part["cid"],
                        "placement": part["placement"],
                        "a": fa,
                        "b": fb,
                    }
                    if part.get("bore_out"):
                        meta["bore_out"] = part["bore_out"]
                    out.append(meta)
                    cursor_t = end_t
                fb_last = (ax + cursor_t * vx, ay + cursor_t * vy, az + cursor_t * vz)
                if _seg_len(fb_last, b) > 1e-6:
                    out.append({"kind": "PIPE", "a": fb_last, "b": b})
                inserted = True
            else:
                out.append(seg)
        if not inserted:
            if chain:
                last = chain[-1]
                la, lb = last["a"], last["b"]
                u = _unit(lb[0] - la[0], lb[1] - la[1], lb[2] - la[2])
                if u == (0.0, 0.0, 0.0):
                    u = (1.0, 0.0, 0.0)
                cursor = lb
                for part in parts:
                    plen = float(part["length_m"])
                    fb = (cursor[0] + u[0] * plen, cursor[1] + u[1] * plen, cursor[2] + u[2] * plen)
                    meta = {
                        "kind": part["kind"],
                        "skey": part["skey"],
                        "tag": part["cid"],
                        "item_code": part["cid"],
                        "placement": part["placement"],
                        "a": cursor,
                        "b": fb,
                    }
                    if part.get("bore_out"):
                        meta["bore_out"] = part["bore_out"]
                    out.append(meta)
                    cursor = fb
            else:
                cursor = pos
                for part in parts:
                    plen = float(part["length_m"])
                    fb = (cursor[0] + plen, cursor[1], cursor[2])
                    out.append(
                        {
                            "kind": part["kind"],
                            "skey": part["skey"],
                            "tag": part["cid"],
                            "item_code": part["cid"],
                            "placement": part["placement"],
                            "a": cursor,
                            "b": fb,
                            **({"bore_out": part["bore_out"]} if part.get("bore_out") else {}),
                        }
                    )
                    cursor = fb
        return out

    # Group consecutive FLANGE–GASKET–FLANGE from expansion into single inserts
    chain = list(spine)
    groups: list[list[dict[str, _Any]]] = []
    i = 0
    while i < len(expanded):
        item = expanded[i]
        if (
            item["kind"] == "FLANGE"
            and i + 2 < len(expanded)
            and expanded[i + 1]["kind"] == "GASKET"
            and expanded[i + 2]["kind"] == "FLANGE"
        ):
            groups.append(expanded[i : i + 3])
            i += 3
        else:
            groups.append([item])
            i += 1
    for group in groups:
        pos = _point_at_station(pts, float(group[0]["station"]))
        chain = _insert_fitting_group(chain, pos, group)

    # Propagate bore_out along chain after REDUCER for subsequent PIPE emit
    current_bore = bore_str
    for seg in chain:
        if seg["kind"] == "REDUCER" and seg.get("bore_out"):
            seg["_bore_a"] = current_bore
            seg["_bore_b"] = f"{bore_to_mm(seg['bore_out']):.1f}"
            current_bore = seg["_bore_b"]
        else:
            seg["_bore_a"] = current_bore
            seg["_bore_b"] = current_bore

    # --- emit ---
    lines: list[str] = []
    lines.append("UNITS-BORE               MM")
    lines.append("UNITS-CO-ORDS            MM")
    lines.append("UNITS-BOLT-LENGTH        MM")
    lines.append("UNITS-WEIGHT             KGS")
    lines.append(f"PIPELINE-REFERENCE       {pipe.line_number}")
    lines.append(f"PIPING-SPEC              {spec}")
    if pipe.service:
        lines.append(f"ATTRIBUTE0               SERVICE {pipe.service}")
    if pipe.material:
        lines.append(f"ATTRIBUTE1               MATERIAL {pipe.material}")
    lines.append(f"ATTRIBUTE2               FROM {pipe.from_tag or 'UNK'}")
    lines.append(f"ATTRIBUTE3               TO {pipe.to_tag or 'UNK'}")
    if fabricated:
        lines.append("ATTRIBUTE9               GEOMETRY FABRICATED")
    lines.append("")

    for seg in chain:
        kind = seg["kind"]
        lines.append(kind)
        bore_a = seg.get("_bore_a") or bore_str
        bore_b = seg.get("_bore_b") or bore_str
        if kind == "REDUCER" and seg.get("bore_out"):
            bore_b = f"{bore_to_mm(seg['bore_out']):.1f}"
            bore_a = seg.get("_bore_a") or bore_str
        lines.append(f"    END-POINT             {_pcf_coord(*seg['a'])} {bore_a}")
        lines.append(f"    END-POINT             {_pcf_coord(*seg['b'])} {bore_b}")
        if kind == "ELBOW":
            lines.append(f"    CENTRE-POINT          {_pcf_coord(*seg['centre'])}")
            lines.append(f"    SKEY                  {seg.get('skey', 'ELBW')}")
            lines.append(f"    ANGLE                 {seg.get('angle', 9000)}")
        elif kind != "PIPE":
            if seg.get("skey"):
                lines.append(f"    SKEY                  {seg['skey']}")
            if seg.get("tag"):
                lines.append(f"    COMPONENT-ATTRIBUTE1  {seg['tag']}")
            if seg.get("item_code"):
                lines.append(f"    ITEM-CODE             {seg['item_code']}")
            if seg.get("placement"):
                lines.append(f"    COMPONENT-ATTRIBUTE2  placement={seg['placement']}")
            if kind == "REDUCER" and seg.get("bore_out"):
                lines.append(f"    COMPONENT-ATTRIBUTE3  bore_out={seg['bore_out']}")
        lines.append(f"    BORE                  {bore_a}")
        lines.append("")

    for s in route.get("supports") or []:
        xyz = s.get("xyz") or [0, 0, 0]
        lines.append("SUPPORT")
        lines.append(f"    CO-ORDS               {_pcf_coord(xyz[0], xyz[1], xyz[2])}")
        lines.append(f"    COMPONENT-ATTRIBUTE1  {s.get('id', 'SUP')}")
        lines.append("")

    lines.append("MATERIALS")
    for cid in pipe.component_tags:
        tag = graph.tags.get(cid)
        ctype = tag.engineering.component_class if tag else "COMP"
        lines.append(f"ITEM-CODE                {cid}")
        lines.append(f"DESCRIPTION              {ctype}")
    lines.append("")
    lines.append("END-OF-FILE")
    lines.append("")
    header_note = (
        "=== <private-repo> PCF (structurally valid subset; not Autodesk-certified) ===\n"
    )
    return header_note + "\n".join(lines)



def generate_pcf(
    graph: TopologyGraph,
    line_id: str,
    output_dir: Optional[Path] = None,
) -> ArtefactDescriptor:
    """Write a minimal valid-ish PCF text file from centerline stubs."""
    pipe = graph.pipelines.get(line_id)
    if pipe is None:
        return ArtefactDescriptor(
            id=_aid("PCF"),
            kind=ArtefactKind.PCF,
            status="failed",
            related_lines=[line_id],
            message=f"Line not found: {line_id}",
        )
    text = write_pcf_text(graph, line_id)
    out_path: Optional[Path] = None
    if output_dir is not None:
        pcf_dir = _ensure_dir(Path(output_dir) / "pcf")
        safe = pipe.line_number.replace("/", "_").replace(" ", "_")
        out_path = pcf_dir / f"{safe}.pcf"
        out_path.write_text(text, encoding="utf-8")

    return ArtefactDescriptor(
        id=_aid("PCF"),
        kind=ArtefactKind.PCF,
        status="ready",
        path=str(out_path) if out_path else f"artefacts/pcf/{pipe.line_number}.pcf",
        related_lines=[line_id],
        related_tags=list(pipe.component_tags),
        payload={
            "format": "PCF-best-effort",
            "line_number": pipe.line_number,
            "materials": pipe.material,
            "geometry_source": get_route(graph, line_id).get("geometry_source", "unknown"),
            "route_length_m": float(get_route(graph, line_id).get("length_m") or 0.0),
            "text_preview": "\n".join(text.splitlines()[:20]),
            "bytes": len(text.encode("utf-8")),
            "wall": "Exact Autodesk ISOGEN PCF schema needs proprietary docs — see WALLS.md",
        },
        message="PCF text written" if out_path else "PCF text generated",
    )


# ---------------------------------------------------------------------------
# GA / plot plan SVG
# ---------------------------------------------------------------------------

def write_ga_svg(graph: TopologyGraph) -> str:
    """2D plot-plan SVG from DesignVolume bounding boxes + equipment tags."""
    vols = list(graph.volumes.values())
    if not vols:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200">'
            '<text x="20" y="40" fill="#333">No design volumes</text></svg>'
        )
    minx = min(v.xmin for v in vols)
    miny = min(v.ymin for v in vols)
    maxx = max(v.xmax for v in vols)
    maxy = max(v.ymax for v in vols)
    pad = 50
    w, h = 900, 600
    span_x = max(maxx - minx, 1e-3)
    span_y = max(maxy - miny, 1e-3)

    def sx(x: float) -> float:
        return pad + (x - minx) / span_x * (w - 2 * pad)

    def sy(y: float) -> float:
        # Y up in plant → SVG Y down
        return h - pad - (y - miny) / span_y * (h - 2 * pad)

    def sh(dy: float) -> float:
        return abs(dy) / span_y * (h - 2 * pad)

    def sw(dx: float) -> float:
        return abs(dx) / span_x * (w - 2 * pad)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        '<rect width="100%" height="100%" fill="#f8fafc"/>',
        f'<text x="{pad}" y="28" fill="#0f172a" font-family="sans-serif" font-size="18" font-weight="bold">'
        f"GA / Plot Plan — {graph.metadata.get('plant', 'plant')}</text>",
        '<text x="50" y="48" fill="#64748b" font-family="sans-serif" font-size="11">'
        "DesignVolume AABB + equipment tags (2D top view)</text>",
    ]
    # Volumes
    for v in vols:
        color = v.color or "#94a3b8"
        if not color.startswith("#") and color.isalpha():
            named = {"blue": "#3b82f6", "purple": "#a855f7", "red": "#ef4444", "orange": "#f97316"}
            color = named.get(color.lower(), "#94a3b8")
        x = sx(v.xmin)
        y = sy(v.ymax)
        ww = sw(v.xmax - v.xmin)
        hh = sh(v.ymax - v.ymin)
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{ww:.1f}" height="{hh:.1f}" '
            f'fill="{color}" fill-opacity="0.25" stroke="{color}" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{x + 6:.1f}" y="{y + 16:.1f}" fill="#0f172a" '
            f'font-family="monospace" font-size="12">{v.id} {v.name}</text>'
        )

    # Equipment markers at volume centroid (or tag volume)
    for eq in graph.equipment.values():
        vol = graph.volumes.get(eq.volume_id) if eq.volume_id else None
        if vol:
            cx = (vol.xmin + vol.xmax) / 2
            cy = (vol.ymin + vol.ymax) / 2
            # offset slightly by hash of id so multiple tags don't stack
            off = (hash(eq.id) % 17) - 8
            cx += off * 0.3
            cy += ((hash(eq.id) // 17) % 11) - 5
        else:
            continue
        parts.append(
            f'<rect x="{sx(cx)-18:.1f}" y="{sy(cy)-10:.1f}" width="36" height="20" '
            f'rx="3" fill="#1e293b" stroke="#fbbf24" stroke-width="1.5"/>'
        )
        label = eq.tag if len(eq.tag) <= 14 else eq.tag[:12] + "…"
        parts.append(
            f'<text x="{sx(cx):.1f}" y="{sy(cy)+4:.1f}" text-anchor="middle" '
            f'fill="#f8fafc" font-family="monospace" font-size="8">{label}</text>'
        )

    # Pipelines from shared graph.routes polylines (top view)
    ensure_routes(graph)
    for pipe in graph.pipelines.values():
        route = graph.routes.get(pipe.id) or {}
        pts = route.get("points") or []
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            parts.append(
                f'<line x1="{sx(a["x"]):.1f}" y1="{sy(a["y"]):.1f}" '
                f'x2="{sx(b["x"]):.1f}" y2="{sy(b["y"]):.1f}" '
                f'stroke="#0ea5e9" stroke-width="1.5" stroke-dasharray="4 3"/>'
            )

    parts.append(
        f'<text x="{pad}" y="{h - 16}" fill="#64748b" font-family="sans-serif" font-size="10">'
        f"volumes={len(vols)} equipment={len(graph.equipment)} lines={len(graph.pipelines)}</text>"
    )
    parts.append("</svg>")
    return "\n".join(parts)


def generate_ga(
    graph: TopologyGraph,
    output_dir: Optional[Path] = None,
) -> ArtefactDescriptor:
    """General Arrangement / plot plan SVG from design volumes."""
    svg = write_ga_svg(graph)
    payload = {
        "equipment_count": len(graph.equipment),
        "volume_count": len(graph.volumes),
        "volumes": [v.model_dump() for v in graph.volumes.values()],
    }
    out_path: Optional[Path] = None
    if output_dir is not None:
        ga_dir = _ensure_dir(Path(output_dir) / "ga")
        out_path = ga_dir / "plot_plan.svg"
        out_path.write_text(svg, encoding="utf-8")
        meta = ga_dir / "plot_plan.json"
        meta.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        payload["files"] = {"svg": str(out_path), "json": str(meta)}

    return ArtefactDescriptor(
        id=_aid("GA"),
        kind=ArtefactKind.GA,
        status="ready",
        path=str(out_path) if out_path else "artefacts/ga/plot_plan.svg",
        related_tags=list(graph.equipment.keys()),
        payload=payload,
        message="GA / plot plan SVG written" if out_path else "GA SVG generated",
    )


def generate_dlb(graph: TopologyGraph, output_dir: Optional[Path] = None) -> ArtefactDescriptor:
    """Deliverable list — sheets + artefact inventory (lightweight, real)."""
    ensure_routes(graph)
    fabricated_lines = []
    for p in graph.pipelines.values():
        r = get_route(graph, p.id)
        if r.get("geometry_source") == "fabricated":
            fabricated_lines.append(p.line_number)
    payload = {
        "sheets": [s.model_dump() for s in graph.sheets.values()],
        "pipelines": [p.line_number for p in graph.pipelines.values()],
        "systems": [s.name for s in graph.systems.values()],
        "fabricated_lines": fabricated_lines,
        "note": "DLB inventory from topology (not a full EDMS package)",
    }
    out_path = None
    if output_dir is not None:
        d = _ensure_dir(Path(output_dir) / "dlb")
        out_path = d / "deliverables.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return ArtefactDescriptor(
        id=_aid("DLB"),
        kind=ArtefactKind.DLB,
        status="ready",
        path=str(out_path) if out_path else "artefacts/dlb/deliverables.json",
        payload=payload,
        message="DLB inventory ready",
    )


def generate_csv_export(
    graph: TopologyGraph,
    output_dir: Optional[Path] = None,
) -> ArtefactDescriptor:
    """CSV tag/line export."""
    tags = [
        {
            "id": t.id,
            "name": t.name,
            "discipline": t.discipline.value,
            "volume_id": t.volume_id,
        }
        for t in graph.tags.values()
    ]
    lines = [
        {
            "id": p.id,
            "line_number": p.line_number,
            "from": p.from_tag,
            "to": p.to_tag,
            "nb": p.nominal_bore,
        }
        for p in graph.pipelines.values()
    ]
    out_path = None
    if output_dir is not None:
        d = _ensure_dir(Path(output_dir) / "csv")
        # Real CSV text
        tag_csv = d / "tags.csv"
        with tag_csv.open("w", encoding="utf-8") as fh:
            fh.write("id,name,discipline,volume_id\n")
            for t in tags:
                fh.write(f"{t['id']},{t['name']},{t['discipline']},{t['volume_id'] or ''}\n")
        line_csv = d / "lines.csv"
        with line_csv.open("w", encoding="utf-8") as fh:
            fh.write("id,line_number,from,to,nb\n")
            for p in lines:
                fh.write(
                    f"{p['id']},{p['line_number']},{p['from'] or ''},{p['to'] or ''},{p['nb'] or ''}\n"
                )
        out_path = tag_csv
    return ArtefactDescriptor(
        id=_aid("CSV"),
        kind=ArtefactKind.CSV,
        status="ready",
        path=str(out_path) if out_path else "artefacts/csv/tags_lines.json",
        payload={"tags": tags, "lines": lines},
        message="CSV export ready",
    )


def write_routes_artefact(graph: TopologyGraph, output_dir: Optional[Path] = None) -> ArtefactDescriptor:
    """Persist shared A* graph.routes to routes.json (single geometry source)."""
    art = generate_routes(graph)
    if output_dir is not None:
        d = _ensure_dir(Path(output_dir) / "routes")
        path = d / "routes.json"
        path.write_text(json.dumps(art.payload, indent=2), encoding="utf-8")
        art.path = str(path)
        art.message = f"Routes written to {path}"
    return art


def generate_supports_stub(graph: TopologyGraph, output_dir: Optional[Path] = None) -> ArtefactDescriptor:
    """Backward-compatible name — placeholder supports along routes."""
    art = generate_supports_from_routes(graph)
    if output_dir is not None:
        d = _ensure_dir(Path(output_dir) / "supports")
        path = d / "supports.json"
        path.write_text(json.dumps(art.payload, indent=2), encoding="utf-8")
        art.path = str(path)
    return art


def build_systems_from_graph(graph: TopologyGraph) -> list[ArtefactDescriptor]:
    arts: list[ArtefactDescriptor] = []
    for sys in graph.systems.values():
        arts.append(
            ArtefactDescriptor(
                id=_aid("SYS"),
                kind=ArtefactKind.SYSTEM,
                status="ready",
                related_tags=list(sys.boundary_tags),
                payload=sys.model_dump(),
                message=f"System {sys.name}",
            )
        )
    return arts


def build_test_packs(graph: TopologyGraph) -> list[TestPack]:
    """Build test packs from system boundaries; stop at isolation valves/blinds/spec-breaks.

    Test pressure = 1.5 × design (B31.3) when DesignPressure is known.
    """
    isolation = {"VALVE-ISOLATION", "BLIND", "SPEC-BREAK", "VALVE-GATE", "BLINDFLANGE"}
    packs: list[TestPack] = []
    for sys in graph.systems.values():
        member_tags: set[str] = set(sys.boundary_tags)
        frontier = list(sys.boundary_tags)
        seen_edges: set[str] = set()
        while frontier:
            cur = frontier.pop()
            for edge in graph.from_tos.values():
                if edge.id in seen_edges:
                    continue
                other = None
                if edge.from_id == cur:
                    other = edge.to_id
                elif edge.to_id == cur:
                    other = edge.from_id
                if other is None:
                    continue
                seen_edges.add(edge.id)
                tag = graph.tags.get(other)
                cls = (tag.engineering.component_class or "").upper().replace(" ", "") if tag else ""
                name_u = (tag.name if tag else other).upper()
                is_iso = cls in isolation or "BLIND" in name_u or cls == "VALVE-ISOLATION"
                member_tags.add(other)
                if is_iso:
                    continue  # do not cross
                frontier.append(other)
        for pipe in graph.pipelines.values():
            if pipe.from_tag in member_tags or pipe.to_tag in member_tags:
                for cid in pipe.component_tags:
                    tag = graph.tags.get(cid)
                    cls = (tag.engineering.component_class or "").upper().replace(" ", "") if tag else ""
                    member_tags.add(cid)
                    if cls in isolation:
                        continue
                if pipe.from_tag:
                    member_tags.add(pipe.from_tag)
                if pipe.to_tag:
                    member_tags.add(pipe.to_tag)
        member_tags = {t for t in member_tags if t in graph.tags}
        # design pressure from any related pipeline metadata
        design_p = None
        for pipe in graph.pipelines.values():
            if pipe.from_tag in member_tags or pipe.to_tag in member_tags:
                dp = (pipe.metadata or {}).get("DesignPressure") or (pipe.metadata or {}).get("design_pressure")
                if dp is not None:
                    design_p = float(dp)
                    break
        tp_val = hydrotest_pressure_barg(design_p)
        meta: dict[str, Any] = {"boundary": list(sys.boundary_tags)}
        if tp_val is not None:
            meta["test_pressure_barg"] = tp_val
            meta["design_pressure_barg"] = design_p
        else:
            meta["test_pressure_status"] = "missing_design_pressure"
        pack = TestPack(
            id=f"TP-{sys.id}",
            name=f"Test Pack {sys.name}",
            system_id=sys.id,
            tags=sorted(member_tags),
            status="draft",
            metadata=meta,
        )
        packs.append(pack)
    return packs


def build_work_packages(
    graph: TopologyGraph,
    wp_type: WPType = WPType.CWP,
) -> list[WorkPackage]:
    """AWP-shaped CWA→CWP→IWP generation.

    - CWA: one per plant / major area
    - CWP: one per design volume × discipline
    - IWP: ≤25 tags and one 5 m elevation band; quantity_measure = kg + m;
      crew-hours from MSS/SP-58-inspired 0.15 h per meter norm (documented).
    """
    # Crew-hours norm: 0.15 h/m of pipe — plant practice placeholder (not a licensed AWP table).
    CREW_HOURS_PER_M = 0.15
    wps: list[WorkPackage] = []
    ensure_routes(graph)

    # CWA
    cwa = WorkPackage(
        id="CWA-PLANT",
        name="Construction Work Area — Plant",
        wp_type=WPType.CWA if hasattr(WPType, "CWA") else wp_type,
        discipline=Discipline.PIP,
        volume_id=None,
        tags=sorted(graph.tags.keys()),
        status="planned",
        quantity_measure="plantwide",
        metadata={"tier": "CWA"},
    )
    if hasattr(WPType, "CWA"):
        wps.append(cwa)
        graph.add_work_package(cwa)

    volumes = list(graph.volumes.values()) or []
    if not volumes:
        # fabricate a single plant volume band for IWP splitting
        from .models import DesignVolume

        volumes = [
            DesignVolume(id="VOL-PLANT", name="Plant", xmin=0, ymin=0, zmin=0, xmax=100, ymax=100, zmax=20)
        ]

    for vol in volumes:
        tags_in_vol = graph.tags_in_volume(vol.id) if vol.id in graph.volumes else list(graph.tags.values())
        by_disc: dict[Discipline, list[str]] = {}
        for t in tags_in_vol:
            by_disc.setdefault(t.discipline, []).append(t.id)
        for disc, tag_ids in by_disc.items():
            cwp = WorkPackage(
                id=f"WP-{vol.id}-{disc.value}",
                name=f"{vol.name} / {disc.value}",
                wp_type=WPType.CWP,
                discipline=disc,
                volume_id=vol.id,
                tags=sorted(tag_ids),
                status="planned",
                quantity_measure=f"{len(tag_ids)} tags",
                metadata={"tier": "CWP", "parent_cwa": "CWA-PLANT"},
            )
            wps.append(cwp)
            graph.add_work_package(cwp)
            # IWP split: ≤25 tags, 5 m elevation bands
            z0 = getattr(vol, "zmin", 0.0) or 0.0
            z1 = getattr(vol, "zmax", z0 + 10.0) or (z0 + 10.0)
            band = 5.0
            band_i = 0
            z = z0
            while z < z1 - 1e-6 or band_i == 0:
                band_tags = tag_ids  # elevation on tags often missing — chunk by 25
                for i in range(0, len(band_tags), 25):
                    chunk = band_tags[i : i + 25]
                    # length/weight from routes for PIP
                    length_m = 0.0
                    weight_kg = 0.0
                    for lid, route in (graph.routes or {}).items():
                        pipe = graph.pipelines.get(lid)
                        if not pipe:
                            continue
                        if pipe.from_tag in chunk or pipe.to_tag in chunk or set(pipe.component_tags) & set(chunk):
                            length_m += float(route.get("length_m") or 0)
                            weight_kg += mass_per_m(pipe.nominal_bore) * float(route.get("length_m") or 0)
                    crew_h = round(length_m * CREW_HOURS_PER_M, 2)
                    iwp = WorkPackage(
                        id=f"IWP-{vol.id}-{disc.value}-B{band_i}-S{i // 25}",
                        name=f"IWP {vol.name} {disc.value} band {band_i}",
                        wp_type=WPType.IWP,
                        discipline=disc,
                        volume_id=vol.id,
                        tags=sorted(chunk),
                        status="planned",
                        quantity_measure=f"{round(weight_kg, 1)} kg + {round(length_m, 2)} m",
                        metadata={
                            "tier": "IWP",
                            "parent_cwp": cwp.id,
                            "elevation_band_m": [z, min(z + band, z1)],
                            "crew_hours": crew_h,
                            "crew_hours_norm": "0.15 h/m plant practice (not licensed AWP table)",
                            "length_m": length_m,
                            "weight_kg": weight_kg,
                        },
                    )
                    wps.append(iwp)
                    graph.add_work_package(iwp)
                band_i += 1
                z += band
                if band_i > 20:
                    break
    return wps



def export_all_piping_artefacts(
    graph: TopologyGraph,
    output_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Write PCF + ISO + routes + GA under output_dir."""
    out = Path(output_dir) if output_dir else default_output_dir()
    _ensure_dir(out)
    results: dict[str, Any] = {"output_dir": str(out), "artefacts": []}
    results["artefacts"].append(write_routes_artefact(graph, out).model_dump(mode="json"))
    results["artefacts"].append(generate_supports_stub(graph, out).model_dump(mode="json"))
    results["artefacts"].append(generate_ga(graph, out).model_dump(mode="json"))
    results["artefacts"].append(generate_quantities(graph, output_dir=out).model_dump(mode="json"))
    results["artefacts"].append(generate_csv_export(graph, out).model_dump(mode="json"))
    results["artefacts"].append(generate_dlb(graph, out).model_dump(mode="json"))
    results["artefacts"].append(generate_clash_report(graph, out).model_dump(mode="json"))
    for lid in graph.pipelines:
        results["artefacts"].append(generate_pcf(graph, lid, out).model_dump(mode="json"))
        results["artefacts"].append(generate_isometric(graph, lid, out).model_dump(mode="json"))
    return results


def regenerate_dirty(
    graph: TopologyGraph,
    dirty_kinds: list[ArtefactKind],
    dirty_wp_ids: Optional[list[str]] = None,
    output_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """Re-run generators for dirty artefact kinds."""
    results: dict[str, Any] = {"regenerated": []}
    out = output_dir
    if ArtefactKind.QUANTITIES in dirty_kinds:
        art = generate_quantities(graph, output_dir=out)
        results["regenerated"].append(art.model_dump())
    if ArtefactKind.ISOMETRIC in dirty_kinds:
        for lid in graph.pipelines:
            art = generate_isometric(graph, lid, output_dir=out)
            results["regenerated"].append(art.model_dump())
    if ArtefactKind.PCF in dirty_kinds:
        for lid in list(graph.pipelines)[:5]:
            art = generate_pcf(graph, lid, output_dir=out)
            results["regenerated"].append(art.model_dump())
    if ArtefactKind.TEST_PACK in dirty_kinds:
        packs = build_test_packs(graph)
        results["test_packs"] = [p.model_dump() for p in packs]
        results["regenerated"].append({"kind": "test_pack", "count": len(packs)})
    if ArtefactKind.WORK_PACKAGE in dirty_kinds:
        if dirty_wp_ids:
            for wid in dirty_wp_ids:
                graph.work_packages.pop(wid, None)
        else:
            graph.work_packages.clear()
        wps = build_work_packages(graph)
        results["work_packages"] = [w.model_dump(mode="json") for w in wps]
        results["regenerated"].append({"kind": "work_package", "count": len(wps)})
    if ArtefactKind.ROUTES in dirty_kinds:
        results["regenerated"].append(write_routes_artefact(graph, out).model_dump())
    if ArtefactKind.SUPPORTS in dirty_kinds:
        results["regenerated"].append(generate_supports_stub(graph, out).model_dump())
    if ArtefactKind.GA in dirty_kinds:
        results["regenerated"].append(generate_ga(graph, out).model_dump())
    if ArtefactKind.DLB in dirty_kinds:
        results["regenerated"].append(generate_dlb(graph, out).model_dump())
    if ArtefactKind.CSV in dirty_kinds:
        results["regenerated"].append(generate_csv_export(graph, out).model_dump())
    return results


def build_iwps(
    graph: TopologyGraph,
    max_tags: int = 25,
    elevation_band_m: float = 5.0,
) -> list[WorkPackage]:
    """Split each CWP into IWPs by tag count ≤ max_tags and elevation band."""
    from .tables import mass_per_m

    ensure_routes(graph)

    iwps: list[WorkPackage] = []
    cwps = [w for w in graph.work_packages.values() if w.wp_type == WPType.CWP]
    for cwp in cwps:
        tags = list(cwp.tags)
        # elevation bands from nozzle/volume z
        def tag_z(tid: str) -> float:
            nz = graph.nozzles.get(tid)
            if nz and nz.z is not None:
                return float(nz.z)
            tag = graph.tags.get(tid)
            if tag and tag.volume_id and tag.volume_id in graph.volumes:
                v = graph.volumes[tag.volume_id]
                return (v.zmin + v.zmax) / 2.0
            return 0.0

        bands: dict[int, list[str]] = {}
        for tid in tags:
            band = int(tag_z(tid) // elevation_band_m)
            bands.setdefault(band, []).append(tid)
        n = 0
        for band, band_tags in sorted(bands.items()):
            for i in range(0, max(len(band_tags), 1), max_tags):
                chunk = band_tags[i : i + max_tags]
                if not chunk:
                    continue
                n += 1
                # quantity from weight + length of related lines
                weight = 0.0
                length = 0.0
                for pipe in graph.pipelines.values():
                    if any(t in chunk for t in pipe.component_tags) or pipe.from_tag in chunk or pipe.to_tag in chunk:
                        r = get_route(graph, pipe.id)
                        length += float(r["length_m"])
                        weight += mass_per_m(pipe.nominal_bore) * float(r["length_m"])
                vol = graph.volumes.get(cwp.volume_id) if cwp.volume_id else None
                cwa = (vol.site or vol.plot_plan_ref or vol.id) if vol else "SITE"
                iwp = WorkPackage(
                    id=f"IWP-{cwp.id}-{n}",
                    name=f"IWP {cwp.name} #{n}",
                    wp_type=WPType.IWP,
                    discipline=cwp.discipline,
                    volume_id=cwp.volume_id,
                    tags=sorted(chunk),
                    status="planned",
                    quantity_measure=f"{weight:.1f} kg / {length:.1f} m",
                    metadata={
                        "parent_cwp": cwp.id,
                        "cwa": cwa,
                        "elevation_band": band,
                        "weight_kg": round(weight, 2),
                        "length_m": round(length, 2),
                    },
                )
                iwps.append(iwp)
                graph.add_work_package(iwp)
    return iwps
