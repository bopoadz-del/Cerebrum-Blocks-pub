# Ported (real) from <private-repo> src/<private-repo>/pcf_strict.py (donor HEAD on disk).
# Intra-package imports are rewritten to relative imports; the code is
# otherwise carried verbatim. DEXPI ingestion is NOT duplicated here: the
# Store's dexpi_ingest block (ported from ingest_dexpi.py) covers ingestion,
# and this package carries the downstream digital thread (graph, routing,
# tables, clash, schedule 4D, generators, PCF, maturity, cascade, exporters).
# The agent/API layers (agent_tools, cli, server, mcp_server) are not ported.
"""Independent strict PCF parser from the public ISOGEN/PCF keyword vocabulary.

Deliberately separate from ``<private-repo>.pcf_reader`` so acceptance A11 does not
round-trip through the writer's own reader.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

# Public PCF / ISOGEN-style keywords commonly emitted by plant design systems.
PCF_KEYWORDS = {
    "ISOGEN-FILES",
    "UNITS-BORE",
    "UNITS-CO-ORDS",
    "UNITS-BOLT-DIA",
    "UNITS-BOLT-LENGTH",
    "UNITS-WEIGHT",
    "PIPELINE-REFERENCE",
    "PIPING-SPEC",
    "NOM-BORE",
    "ITEM-DESCRIPTION",
    "ITEM-CODE",
    "END-POINT",
    "PIPE",
    "ELBOW",
    "BEND",
    "TEE",
    "CAP",
    "FLANGE",
    "GASKET",
    "BOLT",
    "VALVE",
    "REDUCER-CONCENTRIC",
    "REDUCER-ECCENTRIC",
    "SUPPORT",
    "MATERIALS",
    "MATERIAL",
    "MATERIALS-LIST",
    "CENTRE-POINT",
    "BRANCH1-POINT",
    "SKEY",
    "ANGLE",
    "ATTRIBUTE0",
    "ATTRIBUTE1",
    "ATTRIBUTE2",
    "ATTRIBUTE3",
    "ATTRIBUTE4",
    "WELD",
    "MESSAGE",
}


def _parse_floats(parts: list[str]) -> list[float]:
    out: list[float] = []
    for p in parts:
        try:
            out.append(float(p))
        except ValueError:
            break
    return out


def parse_pcf_strict(source: Union[str, Path]) -> dict[str, Any]:
    """Parse a PCF file into header + ordered components (independent of pcf_reader)."""
    path = Path(source)
    text = path.read_text(encoding="utf-8", errors="replace")
    header: dict[str, str] = {}
    components: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    component_kinds = {
        "PIPE",
        "ELBOW",
        "BEND",
        "TEE",
        "CAP",
        "FLANGE",
        "GASKET",
        "VALVE",
        "REDUCER-CONCENTRIC",
        "REDUCER-ECCENTRIC",
        "SUPPORT",
        "WELD",
    }

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("***"):
            continue
        parts = line.split()
        key = parts[0].upper()
        rest = parts[1:]
        if key in ("PIPELINE-REFERENCE", "UNITS-BORE", "UNITS-CO-ORDS", "PIPING-SPEC", "ISOGEN-FILES"):
            header[key] = " ".join(rest)
            current = None
            continue
        if key in component_kinds:
            current = {"kind": key, "end_points": [], "attrs": {}, "raw": [line]}
            components.append(current)
            if rest:
                current["attrs"]["head"] = " ".join(rest)
            continue
        if current is None:
            header[key] = " ".join(rest)
            continue
        current["raw"].append(line)
        if key == "END-POINT":
            nums = _parse_floats(rest)
            if len(nums) >= 3:
                current["end_points"].append({"xyz": nums[:3], "bore": nums[3] if len(nums) > 3 else None})
        elif key in ("CENTRE-POINT", "BRANCH1-POINT"):
            nums = _parse_floats(rest)
            current["attrs"][key] = nums
        elif key == "SKEY":
            current["attrs"]["SKEY"] = " ".join(rest)
        elif key == "ANGLE":
            current["attrs"]["ANGLE"] = " ".join(rest)
        elif key.startswith("ATTRIBUTE"):
            current["attrs"][key] = " ".join(rest)
        elif key == "ITEM-CODE":
            current["attrs"]["ITEM-CODE"] = " ".join(rest)
        else:
            current["attrs"][key] = " ".join(rest)

    # Contiguity check ±1 mm on successive PIPE/ELBOW end-points
    contig_ok = True
    last_end: Optional[list[float]] = None
    for comp in components:
        eps = comp.get("end_points") or []
        if not eps:
            continue
        if last_end is not None:
            dx = abs(eps[0]["xyz"][0] - last_end[0])
            dy = abs(eps[0]["xyz"][1] - last_end[1])
            dz = abs(eps[0]["xyz"][2] - last_end[2])
            if max(dx, dy, dz) > 1.0:  # mm
                contig_ok = False
        last_end = eps[-1]["xyz"]

    return {
        "path": str(path),
        "header": header,
        "components": components,
        "contiguous": contig_ok,
        "keywords_seen": sorted({c["kind"] for c in components}),
    }


def assert_pcf_strict(source: Union[str, Path]) -> dict[str, Any]:
    doc = parse_pcf_strict(source)
    if not doc["components"]:
        raise ValueError(f"no components in {source}")
    if not doc["contiguous"]:
        raise ValueError(f"non-contiguous components in {source}")
    return doc
