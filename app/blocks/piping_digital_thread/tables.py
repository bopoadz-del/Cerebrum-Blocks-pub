# Ported (real) from <private-repo> src/<private-repo>/tables.py (donor HEAD on disk).
# Intra-package imports are rewritten to relative imports; the code is
# otherwise carried verbatim. DEXPI ingestion is NOT duplicated here: the
# Store's dexpi_ingest block (ported from ingest_dexpi.py) covers ingestion,
# and this package carries the downstream digital thread (graph, routing,
# tables, clash, schedule 4D, generators, PCF, maturity, cascade, exporters).
# The agent/API layers (agent_tools, cli, server, mcp_server) are not ported.
"""Public engineering tables (cited). No invented vendor catalogues.

Sources (public / standards summaries commonly republished):
- ASME B36.10M / B36.19M — NPS → OD and schedule wall thickness for steel pipe.
- Steel density 7850 kg/m³ — common engineering value for carbon steel.
- MSS SP-58 — pipe support spacing (water-filled steel pipe) guidance.
- ASME B16.9 — long-radius elbow centreline radius = 1.5 × NPS.
- ASME B16.5 — flange bolt count/size and minimum flange thickness for Class 150 / 300.
- ASME B16.9 — butt-welding fittings: long-radius elbows; concentric reducer end-to-end.
- ASME B16.10 — valve face-to-face / end-to-end dimensions (Class 150 gate / globe).
- Gasket thickness 3 mm — common compressed non-asbestos sheet practice (not a code table).
- ASME B31.3 — hydrostatic test pressure commonly 1.5 × design pressure.
"""

from __future__ import annotations

import math
from typing import Optional

# NPS (inch) → OD (mm). ASME B36.10M Table 1 (selected common sizes).
NPS_OD_MM: dict[float, float] = {
    0.5: 21.3,
    0.75: 26.7,
    1.0: 33.4,
    1.5: 48.3,
    2.0: 60.3,
    3.0: 88.9,
    4.0: 114.3,
    6.0: 168.3,
    8.0: 219.1,
    10.0: 273.0,
    12.0: 323.8,
}

# Schedule → wall thickness mm by NPS. ASME B36.10M (selected).
# Keys: (nps_inch, schedule_name)
WALL_THICKNESS_MM: dict[tuple[float, str], float] = {
    (2.0, "40"): 3.91,
    (3.0, "40"): 5.49,
    (4.0, "40"): 6.02,
    (6.0, "40"): 7.11,
    (8.0, "40"): 8.18,
    (6.0, "80"): 10.97,
    (4.0, "80"): 8.56,
    (2.0, "80"): 5.54,
    (3.0, "80"): 7.62,
}

STEEL_DENSITY_KG_M3 = 7850.0  # carbon steel

# MSS SP-58 suggested support spacing (m) for water-filled CS pipe (approx table).
# Values are commonly republished spans for Sch40 water service.
SUPPORT_SPAN_M: dict[float, float] = {
    0.5: 2.1,
    0.75: 2.4,
    1.0: 2.7,
    1.5: 3.0,
    2.0: 3.4,
    3.0: 4.0,
    4.0: 4.3,
    6.0: 5.2,
    8.0: 5.8,
    10.0: 6.4,
    12.0: 7.0,
}

# ASME B16.5 Class 150 / 300 bolt counts and sizes (UNC).
# (nps, class) → (bolt_count, bolt_dia_inch)
FLANGE_BOLTS: dict[tuple[float, int], tuple[int, float]] = {
    (2.0, 150): (4, 0.625),
    (3.0, 150): (4, 0.625),
    (4.0, 150): (8, 0.625),
    (6.0, 150): (8, 0.75),
    (8.0, 150): (8, 0.75),
    (2.0, 300): (8, 0.625),
    (3.0, 300): (8, 0.75),
    (4.0, 300): (8, 0.75),
    (6.0, 300): (12, 0.75),
    (8.0, 300): (12, 0.875),
}


def parse_nps_inch(nominal_bore: Optional[str]) -> float:
    if not nominal_bore:
        return 4.0
    s = nominal_bore.replace('"', "").replace("''", "").strip().upper()
    s = s.replace("DN", "").replace("NB", "").strip()
    inch_map = {"1/2": 0.5, "3/4": 0.75, "1-1/2": 1.5, "1.5": 1.5}
    if s in inch_map:
        return inch_map[s]
    try:
        v = float(s)
        if v > 30:  # treat as mm DN approx
            return v / 25.4
        return v
    except ValueError:
        return 4.0


def od_mm(nominal_bore: Optional[str]) -> float:
    """Outside diameter mm — ASME B36.10M."""
    nps = parse_nps_inch(nominal_bore)
    if nps in NPS_OD_MM:
        return NPS_OD_MM[nps]
    # nearest
    keys = sorted(NPS_OD_MM)
    nearest = min(keys, key=lambda k: abs(k - nps))
    return NPS_OD_MM[nearest]


def wall_thickness_mm(nominal_bore: Optional[str], schedule: str = "40") -> float:
    """Wall thickness mm — ASME B36.10M schedule table (selected)."""
    nps = parse_nps_inch(nominal_bore)
    sch = str(schedule).replace("Sch", "").replace("SCH", "").replace("S", "").strip() or "40"
    if (nps, sch) in WALL_THICKNESS_MM:
        return WALL_THICKNESS_MM[(nps, sch)]
    # fallback interpolate by OD*0.04
    return od_mm(nominal_bore) * 0.04


def mass_per_m(nominal_bore: Optional[str], schedule: str = "40") -> float:
    """Pipe mass kg/m = ρ × π/4 × (OD² − ID²).

    OD/wall from B36.10; density 7850 kg/m³ (CS).
    """
    od = od_mm(nominal_bore) / 1000.0
    t = wall_thickness_mm(nominal_bore, schedule) / 1000.0
    id_ = od - 2 * t
    area = math.pi / 4.0 * (od * od - id_ * id_)
    return area * STEEL_DENSITY_KG_M3


def support_span_m(nominal_bore: Optional[str]) -> float:
    """Suggested support spacing (m) — MSS SP-58 water-filled CS guidance."""
    nps = parse_nps_inch(nominal_bore)
    if nps in SUPPORT_SPAN_M:
        return SUPPORT_SPAN_M[nps]
    keys = sorted(SUPPORT_SPAN_M)
    nearest = min(keys, key=lambda k: abs(k - nps))
    return SUPPORT_SPAN_M[nearest]


def long_radius_elbow_m(nominal_bore: Optional[str]) -> float:
    """Long-radius elbow centreline radius (m) — ASME B16.9: R = 1.5 × NPS."""
    nps = parse_nps_inch(nominal_bore)
    return 1.5 * nps * 0.0254


def flange_bolts(nominal_bore: Optional[str], flange_class: int = 150) -> tuple[int, float]:
    """(count, bolt_dia_inch) — ASME B16.5 Class 150/300."""
    nps = parse_nps_inch(nominal_bore)
    key = (nps, int(flange_class))
    if key in FLANGE_BOLTS:
        return FLANGE_BOLTS[key]
    # nearest nps
    candidates = [k for k in FLANGE_BOLTS if k[1] == int(flange_class)]
    if not candidates:
        return (8, 0.75)
    nearest = min(candidates, key=lambda k: abs(k[0] - nps))
    return FLANGE_BOLTS[nearest]


def hydrotest_pressure_barg(design_pressure_barg: Optional[float]) -> Optional[float]:
    """Hydrotest = 1.5 × design — ASME B31.3 practice."""
    if design_pressure_barg is None:
        return None
    return 1.5 * float(design_pressure_barg)


# ASME B16.5 Class 150 minimum flange thickness tf (mm) — raised-face welding-neck.
# Citation: ASME B16.5 Pipe Flanges and Flanged Fittings, Table 8 (Class 150), selected NPS.
FLANGE_THICKNESS_MM_CL150: dict[float, float] = {
    0.5: 11.2,
    0.75: 12.7,
    1.0: 14.3,
    1.5: 17.5,
    2.0: 19.1,
    3.0: 22.3,
    4.0: 23.9,   # Table 8 NPS 4
    5.0: 23.9,   # Table 8 NPS 5
    6.0: 25.4,   # Table 8 NPS 6
    8.0: 28.4,   # Table 8 NPS 8
    10.0: 28.6,
    12.0: 30.2,
}

# ASME B16.9 concentric reducer overall length (mm) keyed by (NPS_large, NPS_small).
# Selected rows from ASME B16.9 Table I-1 / I-2 (butt-welding fittings).
REDUCER_LENGTH_MM: dict[tuple[float, float], float] = {
    (3.0, 2.0): 89.0,
    (4.0, 3.0): 102.0,
    (4.0, 2.0): 102.0,
    (6.0, 4.0): 140.0,
    (6.0, 3.0): 140.0,
    (8.0, 6.0): 152.0,
    (8.0, 4.0): 152.0,
    (10.0, 8.0): 178.0,
    (12.0, 10.0): 203.0,
    (12.0, 8.0): 203.0,
}

# ASME B16.10 Class 150 gate valve face-to-face (mm) — flanged ends.
# Selected from ASME B16.10 Table 1 (Class 150).
VALVE_F2F_MM_CL150_GATE: dict[float, float] = {
    0.5: 108.0,
    0.75: 117.0,
    1.0: 127.0,
    1.5: 165.0,
    2.0: 178.0,
    3.0: 203.0,
    4.0: 229.0,
    6.0: 267.0,
    8.0: 292.0,
    10.0: 330.0,
    12.0: 356.0,
}

GASKET_THICKNESS_MM = 3.0  # common compressed sheet practice


def flange_thickness_m(nominal_bore: Optional[str], flange_class: int = 150) -> float:
    """Flange thickness (m) — ASME B16.5 Class 150 minimum tf (selected NPS).

    Citation: ASME B16.5 Pipe Flanges and Flanged Fittings, **Table 8** (Class 150
    minimum flange thickness tf). Class 300 not tabulated here → Class 150 used.
    """
    nps = parse_nps_inch(nominal_bore)
    table = FLANGE_THICKNESS_MM_CL150
    if nps in table:
        return table[nps] / 1000.0
    nearest = min(table, key=lambda k: abs(k - nps))
    return table[nearest] / 1000.0


def gasket_thickness_m() -> float:
    """Gasket thickness (m) — 3 mm compressed non-asbestos sheet practice.

    Not an ASME dimensional table; documented plant/practice default for PCF span.
    """
    return GASKET_THICKNESS_MM / 1000.0


def reducer_face_to_face_m(
    bore_large: Optional[str],
    bore_small: Optional[str] = None,
) -> float:
    """Concentric reducer end-to-end length (m) — ASME B16.9.

    Citation: ASME B16.9 Factory-Made Wrought Buttwelding Fittings, Table I-1/I-2
    overall length for concentric reducers (selected size pairs).
    """
    n_large = parse_nps_inch(bore_large)
    if bore_small is None:
        # one standard size step down
        sizes = sorted(NPS_OD_MM)
        smaller = [s for s in sizes if s < n_large - 1e-9]
        n_small = smaller[-1] if smaller else max(0.5, n_large - 1.0)
    else:
        n_small = parse_nps_inch(bore_small)
    if n_small > n_large:
        n_large, n_small = n_small, n_large
    key = (n_large, n_small)
    if key in REDUCER_LENGTH_MM:
        return REDUCER_LENGTH_MM[key] / 1000.0
    # nearest large
    candidates = [k for k in REDUCER_LENGTH_MM if abs(k[0] - n_large) < 0.6]
    if candidates:
        best = min(candidates, key=lambda k: abs(k[1] - n_small))
        return REDUCER_LENGTH_MM[best] / 1000.0
    return max(0.089, 0.025 * n_large)  # conservative fallback from B16.9 trend


def valve_face_to_face_m(nominal_bore: Optional[str], flange_class: int = 150) -> float:
    """Valve face-to-face (m) — ASME B16.10 Class 150 gate (flanged).

    Citation: ASME B16.10 Face-to-Face and End-to-End Dimensions of Valves,
    Table 1 Class 150 gate valves (selected NPS).
    """
    nps = parse_nps_inch(nominal_bore)
    table = VALVE_F2F_MM_CL150_GATE
    if nps in table:
        return table[nps] / 1000.0
    nearest = min(table, key=lambda k: abs(k - nps))
    return table[nearest] / 1000.0


def next_smaller_bore(nominal_bore: Optional[str]) -> str:
    """Return a one-step-smaller DN/NPS string for reducer bore_out."""
    nps = parse_nps_inch(nominal_bore)
    sizes = sorted(NPS_OD_MM)
    smaller = [s for s in sizes if s < nps - 1e-9]
    if not smaller:
        return "DN40" if nps >= 2 else "DN15"
    s = smaller[-1]
    # Prefer DN labelling when input looked metric
    if nominal_bore and "DN" in nominal_bore.upper():
        return f"DN{int(round(s * 25.4))}"
    # inch string
    if s == int(s):
        return f'{int(s)}"'
    return f'{s}"'
