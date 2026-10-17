"""VDC clash detection — AABB intersection.

Donor: C:\\Users\\<owner>\\Cerebrum\\backend\\app\\vdc\\clash_detection.py
Symbols ported: ClashDetectionEngine._calculate_intersection, intersects check,
DEFAULT hard-clash and clearance rules.
Left behind: numpy, IFC ModelElement, AABB tree, thread pool, uuid minting.
Classification: verified_executable (see tests/test_wave2_clones.py).
Persistence: none. Each call is pure.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.universal_base import UniversalBlock

Vec = Sequence[float]


def _vec(value: Any) -> Optional[Tuple[float, float, float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    out = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return None
        out.append(float(item))
    return (out[0], out[1], out[2])


def intersection(a_min: Vec, a_max: Vec, b_min: Vec, b_max: Vec):
    """Donor _calculate_intersection. None when the boxes do not overlap."""
    lo = tuple(max(a_min[i], b_min[i]) for i in range(3))
    hi = tuple(min(a_max[i], b_max[i]) for i in range(3))
    if lo[0] >= hi[0] or lo[1] >= hi[1] or lo[2] >= hi[2]:
        return None
    dims = tuple(hi[i] - lo[i] for i in range(3))
    volume = dims[0] * dims[1] * dims[2]
    center = tuple((lo[i] + hi[i]) / 2 for i in range(3))
    penetration = max(dims)
    return volume, center, penetration


DEFAULT_RULES = (
    {
        "name": "Structural-Architectural Hard Clash",
        "clash_type": "hard_clash",
        "types_a": ("IfcColumn", "IfcBeam"),
        "types_b": ("IfcWall", "IfcDoor", "IfcWindow"),
        "disciplines_a": ("structural",),
        "disciplines_b": ("architectural",),
        "severity": "critical",
        "clearance": 0.0,
    },
    {
        "name": "MEP Clearance",
        "clash_type": "clearance",
        "types_a": ("IfcDistributionElement",),
        "types_b": ("IfcWall", "IfcSlab"),
        "disciplines_a": (),
        "disciplines_b": (),
        "severity": "medium",
        "clearance": 0.05,
    },
)


def _rule_applies(rule: Dict, a: Dict, b: Dict) -> bool:
    def types_match(left, right) -> bool:
        return (
            left.get("element_type") in rule["types_a"]
            and right.get("element_type") in rule["types_b"]
        )
    if not (types_match(a, b) or types_match(b, a)):
        return False
    if rule["disciplines_a"] and a.get("discipline") not in rule["disciplines_a"]:
        if b.get("discipline") not in rule["disciplines_a"]:
            return False
    if rule["disciplines_b"] and b.get("discipline") not in rule["disciplines_b"]:
        if a.get("discipline") not in rule["disciplines_b"]:
            return False
    return True


class VdcClashDetectionBlock(UniversalBlock):
    """AABB clash check. Does not read a model file and does not invent clashes."""

    name = "vdc_clash_detection"
    version = "1.0.0"
    classification = "verified_executable"
    requires: List[str] = []
    layer = 2
    tags = ["vdc", "bim", "clash"]
    default_config: Dict[str, Any] = {}
    ui_schema = {
        "input": {"type": "json"},
        "output": {"type": "json"},
        "params": [{"name": "action", "type": "select", "options": ["detect"], "default": "detect"}],
        "quick_actions": [],
    }

    async def process(self, input_data: Dict, params: Dict = None) -> Dict:
        action = (params or {}).get("action") or (input_data or {}).get("action") or "detect"
        if action != "detect":
            return {"status": "error", "error": f"Unknown action: {action}"}
        return self.detect((input_data or {}).get("elements") or [])

    def detect(self, elements: List[Dict]) -> Dict:
        usable = []
        skipped = []
        for element in elements:
            lo = _vec(element.get("min"))
            hi = _vec(element.get("max"))
            if not element.get("id") or lo is None or hi is None:
                skipped.append(element.get("id"))
                continue
            usable.append((element, lo, hi))
        clashes = []
        for i, (a, a_min, a_max) in enumerate(usable):
            for b, b_min, b_max in usable[i + 1:]:
                hit = intersection(a_min, a_max, b_min, b_max)
                if hit is None:
                    continue
                volume, center, penetration = hit
                for rule in DEFAULT_RULES:
                    if not _rule_applies(rule, a, b):
                        continue
                    if rule["clash_type"] == "clearance" and penetration >= rule["clearance"]:
                        continue
                    pair = tuple(sorted((str(a["id"]), str(b["id"]))))
                    clashes.append({
                        "id": f"{pair[0]}|{pair[1]}|{rule['clash_type']}",
                        "rule": rule["name"],
                        "clash_type": rule["clash_type"],
                        "severity": rule["severity"],
                        "element_a": a["id"],
                        "element_b": b["id"],
                        "intersection_volume": volume,
                        "intersection_center": list(center),
                        "penetration_depth": penetration,
                    })
                    break
        return {
            "status": "ok",
            "total_elements_checked": len(usable),
            "skipped": skipped,
            "clashes": clashes,
        }
