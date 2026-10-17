# Ported (real) from <private-repo> src/<private-repo>/pcf_reader.py (donor HEAD on disk).
# Intra-package imports are rewritten to relative imports; the code is
# otherwise carried verbatim. DEXPI ingestion is NOT duplicated here: the
# Store's dexpi_ingest block (ported from ingest_dexpi.py) covers ingestion,
# and this package carries the downstream digital thread (graph, routing,
# tables, clash, schedule 4D, generators, PCF, maturity, cascade, exporters).
# The agent/API layers (agent_tools, cli, server, mcp_server) are not ported.
"""Strict best-effort PCF grammar parser (public structural subset).

Not Autodesk-certified. Parses UNIT headers, PIPELINE-REFERENCE, PIPE / ELBOW /
fitting blocks with END-POINT / CENTRE-POINT / SKEY / ANGLE, MATERIALS, SUPPORT.
Coordinates are millimetres; bore is MM.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union


@dataclass
class PCFEndPoint:
    x: float
    y: float
    z: float
    bore: Optional[float] = None

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def dist_mm(self, other: "PCFEndPoint") -> float:
        return math.sqrt(
            (self.x - other.x) ** 2 + (self.y - other.y) ** 2 + (self.z - other.z) ** 2
        )


@dataclass
class PCFComponent:
    kind: str  # PIPE | ELBOW | FLANGE | GASKET | VALVE | REDUCER | TEE | SUPPORT | OTHER
    end_points: list[PCFEndPoint] = field(default_factory=list)
    centre_point: Optional[tuple[float, float, float]] = None
    skey: Optional[str] = None
    angle: Optional[int] = None
    bore: Optional[float] = None
    tag: Optional[str] = None
    item_code: Optional[str] = None
    attrs: dict[str, str] = field(default_factory=dict)
    co_ords: Optional[tuple[float, float, float]] = None

    def length_mm(self) -> float:
        if self.kind == "ELBOW" and self.centre_point and len(self.end_points) >= 2:
            # Arc length ≈ R * theta; R from centre to end, theta from ANGLE or 90°
            r = math.sqrt(
                sum((self.end_points[0].as_tuple()[i] - self.centre_point[i]) ** 2 for i in range(3))
            )
            if self.angle is not None:
                theta = abs(self.angle) / 100.0 * math.pi / 180.0
            else:
                # infer from vectors
                a = self.end_points[0].as_tuple()
                b = self.end_points[1].as_tuple()
                c = self.centre_point
                v1 = tuple(a[i] - c[i] for i in range(3))
                v2 = tuple(b[i] - c[i] for i in range(3))
                n1 = math.sqrt(sum(x * x for x in v1)) or 1.0
                n2 = math.sqrt(sum(x * x for x in v2)) or 1.0
                dot = max(-1.0, min(1.0, sum(v1[i] * v2[i] for i in range(3)) / (n1 * n2)))
                theta = math.acos(dot)
            return r * theta
        if len(self.end_points) >= 2:
            return self.end_points[0].dist_mm(self.end_points[1])
        return 0.0


@dataclass
class PCFDocument:
    headers: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, str] = field(default_factory=dict)
    pipeline_reference: Optional[str] = None
    piping_spec: Optional[str] = None
    components: list[PCFComponent] = field(default_factory=list)
    materials: list[tuple[str, str]] = field(default_factory=list)  # item_code, description
    raw_lines: list[str] = field(default_factory=list)


_COMPONENT_START = re.compile(
    r"^(PIPE|ELBOW|FLANGE|GASKET|VALVE|REDUCER|TEE|SUPPORT|CAP|OLET|INSTRUMENT)\b",
    re.I,
)
_END_POINT = re.compile(
    r"END-POINT\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)"
    r"(?:\s+(\d+(?:\.\d+)?))?",
    re.I,
)
_CENTRE = re.compile(
    r"CENTRE-POINT\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)",
    re.I,
)
_COORDS = re.compile(
    r"CO-ORDS\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)",
    re.I,
)
_SKEY = re.compile(r"SKEY\s+(\S+)", re.I)
_ANGLE = re.compile(r"ANGLE\s+(-?\d+)", re.I)
_BORE = re.compile(r"BORE\s+(\d+(?:\.\d+)?)", re.I)
_ITEM = re.compile(r"ITEM-CODE\s+(.+)$", re.I)
_ATTR1 = re.compile(r"COMPONENT-ATTRIBUTE1\s+(.+)$", re.I)
_MAT = re.compile(r"MATERIALS?\s+(.+)$", re.I)
_MAT_LIST = re.compile(r"MATERIALS-LIST\s+(\S+)\s+(.+)$", re.I)


class PCFParseError(ValueError):
    pass


def parse_pcf(text_or_path: Union[str, Path]) -> PCFDocument:
    """Parse PCF text or a file path into a PCFDocument."""
    if isinstance(text_or_path, Path) or (
        isinstance(text_or_path, str)
        and "\n" not in text_or_path
        and Path(text_or_path).exists()
    ):
        text = Path(text_or_path).read_text(encoding="utf-8")
    else:
        text = str(text_or_path)

    doc = PCFDocument(raw_lines=text.splitlines())
    current: Optional[PCFComponent] = None
    in_materials = False

    def flush() -> None:
        nonlocal current
        if current is not None:
            doc.components.append(current)
            current = None

    for raw in doc.raw_lines:
        line = raw.strip()
        if not line or line.startswith("==="):
            continue
        if line.upper().startswith("END-OF-FILE"):
            flush()
            break

        # Header / units / pipeline
        if line.upper().startswith("PIPELINE-REFERENCE"):
            flush()
            doc.pipeline_reference = line.split(None, 1)[1].strip() if " " in line else None
            continue
        if line.upper().startswith("PIPING-SPEC"):
            doc.piping_spec = line.split(None, 1)[1].strip() if " " in line else None
            continue
        if line.upper().startswith("UNITS-") or line.upper().startswith("ISOGEN-FILES"):
            parts = line.split(None, 1)
            doc.headers[parts[0]] = parts[1].strip() if len(parts) > 1 else ""
            continue
        if line.upper().startswith("ATTRIBUTE"):
            parts = line.split(None, 1)
            key = parts[0]
            doc.attributes[key] = parts[1].strip() if len(parts) > 1 else ""
            continue

        if line.upper() == "MATERIALS" or line.upper().startswith("MATERIALS "):
            flush()
            in_materials = True
            # inline MATERIAL item on same line?
            rest = line[9:].strip()
            if rest:
                bits = rest.split(None, 1)
                doc.materials.append((bits[0], bits[1] if len(bits) > 1 else ""))
            continue

        if in_materials:
            mlist = _MAT_LIST.match(line)
            if mlist:
                doc.materials.append((mlist.group(1), mlist.group(2).strip()))
                continue
            # ITEM-CODE / DESCRIPTION pairs
            if line.upper().startswith("ITEM-CODE"):
                code = line.split(None, 1)[1].strip() if " " in line else ""
                doc.materials.append((code, ""))
                continue
            if line.upper().startswith("DESCRIPTION") and doc.materials:
                desc = line.split(None, 1)[1].strip() if " " in line else ""
                code, _ = doc.materials[-1]
                doc.materials[-1] = (code, desc)
                continue
            # leaving materials on new component
            if _COMPONENT_START.match(line):
                in_materials = False
            else:
                continue

        mlist = _MAT_LIST.match(line)
        if mlist:
            flush()
            doc.materials.append((mlist.group(1), mlist.group(2).strip()))
            continue

        m = _COMPONENT_START.match(line)
        if m:
            flush()
            current = PCFComponent(kind=m.group(1).upper())
            continue

        if current is None:
            continue

        ep = _END_POINT.search(line)
        if ep:
            bore = float(ep.group(4)) if ep.group(4) else current.bore
            current.end_points.append(
                PCFEndPoint(float(ep.group(1)), float(ep.group(2)), float(ep.group(3)), bore)
            )
            if bore is not None:
                current.bore = bore
            continue
        cp = _CENTRE.search(line)
        if cp:
            current.centre_point = (float(cp.group(1)), float(cp.group(2)), float(cp.group(3)))
            continue
        co = _COORDS.search(line)
        if co:
            current.co_ords = (float(co.group(1)), float(co.group(2)), float(co.group(3)))
            continue
        sk = _SKEY.search(line)
        if sk:
            current.skey = sk.group(1)
            continue
        ang = _ANGLE.search(line)
        if ang:
            current.angle = int(ang.group(1))
            continue
        br = _BORE.search(line)
        if br:
            current.bore = float(br.group(1))
            continue
        it = _ITEM.search(line)
        if it:
            current.item_code = it.group(1).strip()
            continue
        a1 = _ATTR1.search(line)
        if a1:
            current.tag = a1.group(1).strip()
            continue
        # generic ATTR
        if line.upper().startswith("COMPONENT-ATTRIBUTE"):
            parts = line.split(None, 1)
            current.attrs[parts[0]] = parts[1].strip() if len(parts) > 1 else ""

    flush()
    return doc


def assert_contiguous(doc: PCFDocument, tol_mm: float = 1.0) -> None:
    """Each component's first END-POINT equals previous component's last END-POINT within tol."""
    positioned = [c for c in doc.components if c.kind != "SUPPORT" and c.end_points]
    if not positioned:
        raise PCFParseError("no positioned components")
    for prev, cur in zip(positioned, positioned[1:]):
        last = prev.end_points[-1]
        first = cur.end_points[0]
        d = last.dist_mm(first)
        if d > tol_mm:
            raise PCFParseError(
                f"gap {d:.3f} mm between {prev.kind}@{last.as_tuple()} and "
                f"{cur.kind}@{first.as_tuple()} (tol={tol_mm})"
            )


def total_centreline_length_mm(doc: PCFDocument) -> float:
    """Sum centreline lengths for PIPE/ELBOW and non-zero fittings (excludes SUPPORT)."""
    total = 0.0
    for c in doc.components:
        if c.kind == "SUPPORT":
            continue
        total += c.length_mm()
    return total


def assert_no_zero_length(doc: PCFDocument, tol_mm: float = 0.5) -> None:
    """Raise if any non-SUPPORT component has zero length (E4)."""
    for c in doc.components:
        if c.kind == "SUPPORT":
            continue
        if c.length_mm() < tol_mm:
            raise PCFParseError(
                f"zero-length {c.kind} tag={c.tag} ends={[ep.as_tuple() for ep in c.end_points]}"
            )


def assert_gasket_flanked_by_flanges(doc: PCFDocument) -> None:
    """Every GASKET must be immediately between two FLANGE components."""
    positioned = [c for c in doc.components if c.kind != "SUPPORT"]
    for i, c in enumerate(positioned):
        if c.kind != "GASKET":
            continue
        if i == 0 or i == len(positioned) - 1:
            raise PCFParseError(f"GASKET at edge of chain tag={c.tag}")
        prev, nxt = positioned[i - 1], positioned[i + 1]
        if prev.kind != "FLANGE" or nxt.kind != "FLANGE":
            raise PCFParseError(
                f"GASKET not flanked by FLANGE (prev={prev.kind}, next={nxt.kind}) tag={c.tag}"
            )


def bore_continuity(doc: PCFDocument, allow_at: Optional[set[str]] = None) -> list[str]:
    """Return list of bore discontinuity messages; reducers allowed to change bore."""
    allow_at = allow_at or {"REDUCER"}
    msgs: list[str] = []
    positioned = [c for c in doc.components if c.end_points and c.kind != "SUPPORT"]
    prev_bore: Optional[float] = None
    prev_kind: Optional[str] = None
    for c in positioned:
        for i, ep in enumerate(c.end_points):
            if ep.bore is None:
                continue
            if prev_bore is not None and abs(ep.bore - prev_bore) > 0.05:
                # Allow change on the reducer itself, or the first endpoint after a reducer
                allowed = c.kind in allow_at or prev_kind in allow_at
                if not allowed:
                    msgs.append(
                        f"bore jump {prev_bore} → {ep.bore} at {c.kind} tag={c.tag}"
                    )
            prev_bore = ep.bore
        prev_kind = c.kind
    return msgs


def overlaps_pipe_elbow(doc: PCFDocument, tol_mm: float = 1.0) -> list[str]:
    """Detect ELBOW whose END-POINTS coincide with far ends of adjacent PIPEs (legacy bug)."""
    msgs: list[str] = []
    comps = [c for c in doc.components if c.kind in ("PIPE", "ELBOW") and c.end_points]
    for i, c in enumerate(comps):
        if c.kind != "ELBOW" or len(c.end_points) < 2 or not c.centre_point:
            continue
        # Legacy bug: elbow ends == far ends of neighbouring full pipes
        for j, p in enumerate(comps):
            if p.kind != "PIPE" or len(p.end_points) < 2:
                continue
            # if elbow end equals a pipe end that is NOT the shared tangent near centre
            for ep in c.end_points:
                for pe in p.end_points:
                    if ep.dist_mm(pe) <= tol_mm:
                        # check if this pipe end is far from centre (full-leg overlap)
                        centre = PCFEndPoint(*c.centre_point)
                        if pe.dist_mm(centre) > tol_mm + 1.0:
                            # pipe end coincides with elbow end but is away from centre
                            # → likely overlapping full leg if pipe also reaches centre
                            other = p.end_points[0] if pe is p.end_points[1] else p.end_points[1]
                            if other.dist_mm(centre) <= tol_mm:
                                msgs.append(
                                    f"ELBOW overlaps PIPE leg: elbow_end={ep.as_tuple()} "
                                    f"pipe=({p.end_points[0].as_tuple()}→{p.end_points[1].as_tuple()})"
                                )
    return msgs


def summarise(doc: PCFDocument) -> dict[str, Any]:
    return {
        "pipeline_reference": doc.pipeline_reference,
        "component_counts": {
            k: sum(1 for c in doc.components if c.kind == k)
            for k in sorted({c.kind for c in doc.components})
        },
        "total_length_mm": total_centreline_length_mm(doc),
        "materials": len(doc.materials),
        "has_isogen_files": "ISOGEN-FILES" in doc.headers,
    }
