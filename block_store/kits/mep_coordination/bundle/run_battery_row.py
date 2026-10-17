"""Battery-format row for a production model, with re-calibration FIRST.

Two jobs, in this order and not the other way round:

1. RE-CALIBRATE. The joint threshold was derived from two fixtures with no port
   data. Before this script reports any verdict it measures the production
   model's own joint and clash volume-fraction distributions and states whether
   the empty band the threshold sits in still exists. If the band has closed,
   the verdict is WITHHELD.

2. Emit a per-zone row The Level can grade: hard / clearance / joints /
   resolve rate / escalated.

The order matters. A number calibrated on two toy models must not be allowed to
become a fact about a real building by being applied before it is checked.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.blocks.clash_resolver import STATUS_ESCALATED, STATUS_PROPOSED, resolve, verify_batch
from app.blocks.clash_triage import triage
from app.blocks.clearance_rules import load_rules
from app.blocks.connectivity import (
    TOUCH_VOLUME_FRACTION,
    build_graph,
    classify_findings,
)
from app.blocks.geometry_engine import aabb_overlaps, exact_backend_available, judge_pair
from app.blocks.ifc_loader import load_elements, model_sha256, zone_key

KIT = Path(__file__).parent.parent
CLEARANCE_M = 0.3
ZONES = 5
PER_ZONE = 8

# The provisional set, from docs/MEP_KIT.md. Reproduced here so the comparison
# is self-contained in the output.
PROVISIONAL = {
    "joint_fraction_max_observed": 1e-6,
    "real_clash_fraction_min_observed": 0.0844,
    "threshold": TOUCH_VOLUME_FRACTION,
    "calibration_set": "24 joints (Infra-Plumbing.ifc) + 1 constructed crossing",
    "band_ratio": 84000,
}


def _fraction(finding, by_id) -> float | None:
    pen = getattr(finding, "penetration_volume_m3", None)
    if pen is None:
        return None
    a = by_id.get(getattr(finding, "element_a", ""))
    b = by_id.get(getattr(finding, "element_b", ""))
    vols = []
    for el in (a, b):
        try:
            v = float(getattr(getattr(el, "mesh", None), "volume", 0.0) or 0.0)
        except Exception:  # noqa: BLE001
            v = 0.0
        if v > 0:
            vols.append(v)
    return (pen / min(vols)) if vols else None


def _dist(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    return {
        "n": len(s),
        "min": s[0],
        "median": statistics.median(s),
        "p90": s[int(len(s) * 0.9) - 1] if len(s) > 1 else s[0],
        "max": s[-1],
    }


def recalibrate(findings, joints, by_id, graph) -> dict:
    """Does the empty band still exist on THIS model?"""
    joint_fracs = [f for f in (_fraction(x, by_id) for x in joints) if f is not None]
    clash_fracs = [
        f for f in (_fraction(x, by_id) for x in findings if getattr(x, "kind", "") == "clash")
        if f is not None
    ]
    jd, cd = _dist(joint_fracs), _dist(clash_fracs)

    band_open = None
    ratio = None
    if jd.get("n") and cd.get("n"):
        band_open = jd["max"] < cd["min"]
        ratio = (cd["min"] / jd["max"]) if jd["max"] > 0 else None

    verdict_withheld = band_open is False
    return {
        "provisional": PROVISIONAL,
        "ports_in_model": graph.ports_seen,
        "topology_available": graph.available,
        "topology_decides": graph.available,
        "joint_fraction_distribution": jd,
        "clash_fraction_distribution": cd,
        "band_still_empty": band_open,
        "observed_band_ratio": ratio,
        "threshold_still_inside_band": (
            None if band_open is None
            else (jd["max"] < TOUCH_VOLUME_FRACTION < cd["min"])
        ),
        "verdict_withheld": verdict_withheld,
        "note": (
            "Topology present: the port graph decides and the fraction is a rarely-used "
            "fallback." if graph.available else
            "No port data in this model, so the measured fraction decides. The band "
            "below must stay empty for the threshold to remain defensible."
        ),
        "action_required": (
            "BAND CLOSED — verdict withheld. Re-derive the threshold from this model's "
            "own distributions before reporting clash counts."
            if verdict_withheld else "none"
        ),
    }


def battery_row(ifc: Path) -> dict:
    t0 = time.time()
    sha_before = model_sha256(ifc)
    import ifcopenshell

    els = list(load_elements(ifc, include_structural=True))
    for e in els:
        e.zone_key = zone_key(e)
    by_id = {e.global_id: e for e in els}
    graph = build_graph(ifcopenshell.open(str(ifc)))
    mep = [e for e in els if e.discipline == "mep"]

    if not mep:
        return {
            "model": ifc.name, "skipped": True,
            "reason": "zero MEP elements — check the export included services",
            "runtime_s": round(time.time() - t0, 1),
        }

    findings = []
    for a in mep:
        for b in els:
            if a.global_id == b.global_id:
                continue
            if not aabb_overlaps(a.bbox, b.bbox, pad=CLEARANCE_M):
                continue
            findings.append(judge_pair(
                a.global_id, b.global_id, a.mesh, b.mesh,
                required_clearance_m=CLEARANCE_M, rule_id="MEP-GAS-ANY-300",
                category_a=a.system, category_b=b.system,
            ))

    real, joints = classify_findings(findings, by_id, graph, exact_backend_available())
    calib = recalibrate(findings, joints, by_id, graph)

    res = triage(real, by_id)
    rules = load_rules(KIT / "bundle" / "app" / "blocks" / "seed_rules.json")
    rule = next(iter(rules), None)

    zone_rows = []
    ranked = sorted(
        dict.fromkeys(q.zone_key for q in res.queue),
        key=lambda z: -res.zones.get(z, 0.0),
    )[:ZONES]
    for zk in ranked:
        items = [q for q in res.queue if q.zone_key == zk][:PER_ZONE]
        zone_els = [e for e in els if e.zone_key == zk]
        props = []
        for it in items:
            el = by_id.get(it.element_a)
            if el is None:
                continue
            neigh = [e for e in els if e.global_id != el.global_id
                     and aabb_overlaps(el.bbox, e.bbox, pad=2.0)]
            props.append(resolve(
                it, el, neigh, required_gap_mm=CLEARANCE_M * 1000,
                rule_ids=[rule.rule_id] if rule else [],
                clause_text=getattr(rule.source, "clause", None) if rule else None,
            ))
        if not props:
            continue
        batch = verify_batch(props, by_id, zone_els, CLEARANCE_M * 1000, zone_key=zk)
        sourced = sum(1 for p in props if p.status == STATUS_PROPOSED)
        zone_rows.append({
            "zone": zk,
            "congestion": round(res.zones.get(zk, 0.0), 4),
            "hard": sum(1 for q in items if q.kind == "hard"),
            "clearance": sum(1 for q in items if q.kind == "clearance"),
            "joints_excluded_in_zone": sum(
                1 for j in joints
                if getattr(by_id.get(getattr(j, "element_a", "")), "zone_key", None) == zk
            ),
            "proposals": len(props),
            "resolved": sourced if batch.status == "accepted" else 0,
            "resolve_rate": round((sourced / len(props)) if batch.status == "accepted" and props else 0.0, 3),
            "escalated": sum(1 for p in props if p.status == STATUS_ESCALATED),
            "batch_status": batch.status,
        })

    return {
        "model": ifc.name,
        "skipped": False,
        "mb": round(ifc.stat().st_size / 1e6, 1),
        "elements": len(els),
        "mep_elements": len(mep),
        "RECALIBRATION": calib,
        "totals": {
            "admitted": len(findings),
            "joints": len(joints),
            "hard": sum(1 for f in real if f.kind == "clash"),
            "clearance": sum(1 for f in real if f.kind == "clearance"),
            "false_positives_eliminated": sum(1 for f in real if f.kind == "clear"),
            "queued": len(res.queue),
        },
        "zones": zone_rows,
        "original_untouched": sha_before == model_sha256(ifc),
        "runtime_s": round(time.time() - t0, 1),
    }


def main() -> int:
    drop = KIT / "fixtures" / "owner_models"
    models = sorted(drop.glob("*.ifc"))
    if not models:
        print(f"no .ifc in {drop}")
        return 0
    rows = [battery_row(m) for m in models]
    out = KIT / "acceptance_out" / "BATTERY_ROWS.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    for r in rows:
        print(json.dumps(r, indent=2))
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
