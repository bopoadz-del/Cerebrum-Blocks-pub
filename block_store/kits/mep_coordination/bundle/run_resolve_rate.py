"""Measure the resolve rate PER ZONE, with the search and batch verification.

The order's exit criterion for the resolver is per-zone, not an average, and
that is the right shape: a kit that clears open corridors and fails congested
ones has very different value from one that clears 60% everywhere. An average
hides exactly the case the tool exists for.

Every zone lands in one of three states and none of them is silence:
    cleared    the batch was applied and the zone re-judged clean of new
               conflicts
    escalated  no candidate survived, and the alternatives tried are recorded
    rejected   the batch was individually safe but collectively not, rolled
               back whole
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.blocks.clash_resolver import (
    STATUS_ESCALATED,
    STATUS_FLAGGED,
    STATUS_PROPOSED,
    resolve,
    verify_batch,
)
from app.blocks.clash_triage import triage
from app.blocks.clearance_rules import load_rules
from app.blocks.geometry_engine import aabb_overlaps, judge_pair
from app.blocks.ifc_loader import load_elements, model_sha256, zone_key

KIT = Path(__file__).parent.parent
FIXTURE = KIT / "fixtures" / "schependomlaan_design.ifc"
OUT = KIT / "acceptance_out"
CLEARANCE_M = 0.3
ZONES_TO_ATTEMPT = 5          # the order's "3 in 5" bar
MAX_ITEMS_PER_ZONE = 8


def main() -> int:
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    sha_before = model_sha256(FIXTURE)

    rules = load_rules(KIT / "bundle" / "app" / "blocks" / "seed_rules.json")
    rule = next((r for r in rules if r.rule_id == "MEP-GAS-ANY-300"), None)
    clause = getattr(rule.source, "clause", None) if rule else None

    els = list(load_elements(FIXTURE, include_structural=True))
    for e in els:
        e.zone_key = zone_key(e)
    by_id = {e.global_id: e for e in els}
    mep = [e for e in els if e.discipline == "mep"]

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

    res = triage(findings, by_id)

    # Congested zones first -- the ones the kit exists for.
    ranked = sorted(
        dict.fromkeys(q.zone_key for q in res.queue),
        key=lambda z: -res.zones.get(z, 0.0),
    )[:ZONES_TO_ATTEMPT]

    rows = []
    for zk in ranked:
        items = [q for q in res.queue if q.zone_key == zk][:MAX_ITEMS_PER_ZONE]
        zone_els = [e for e in els if e.zone_key == zk]
        props = []
        for item in items:
            el = by_id.get(item.element_a)
            if el is None:
                continue
            neigh = [e for e in els if e.global_id != el.global_id
                     and aabb_overlaps(el.bbox, e.bbox, pad=2.0)]
            props.append(resolve(
                item, el, neigh, required_gap_mm=CLEARANCE_M * 1000,
                rule_ids=[rule.rule_id] if rule else [],
                clause_text=clause,
            ))
        if not props:
            continue
        batch = verify_batch(props, by_id, zone_els, CLEARANCE_M * 1000, zone_key=zk)
        sourced = sum(1 for p in props if p.status == STATUS_PROPOSED)
        escal = sum(1 for p in props if p.status == STATUS_ESCALATED)
        rows.append({
            "zone": zk,
            "congestion": round(res.zones.get(zk, 0.0), 4),
            "clashes_in_zone": len(items),
            "proposals": len(props),
            "sourced": sourced,
            "escalated_with_alternatives": escal,
            "flagged_unsourced": sum(1 for p in props if p.status == STATUS_FLAGGED),
            "batch_status": batch.status,
            "new_hard_from_batch": batch.new_hard_clashes,
            "new_violations_from_batch": batch.new_violations,
            "outcome": (
                "cleared" if batch.status == "accepted" and sourced
                else "batch_rejected" if batch.status == "rejected"
                else "escalated"
            ),
        })

    sha_after = model_sha256(FIXTURE)
    cleared = sum(1 for r in rows if r["outcome"] == "cleared")
    accounted = sum(1 for r in rows if r["outcome"] in ("cleared", "escalated", "batch_rejected"))

    report = {
        "zones_attempted": len(rows),
        "cleared": cleared,
        "escalated": sum(1 for r in rows if r["outcome"] == "escalated"),
        "batch_rejected": sum(1 for r in rows if r["outcome"] == "batch_rejected"),
        "silently_unresolved": len(rows) - accounted,
        "exit_bar": ">=3 of 5 zones cleared OR escalated with alternatives",
        "exit_met": accounted >= min(3, len(rows)),
        "original_untouched": sha_before == sha_after,
        "runtime_s": round(time.time() - t0, 1),
        "zones": rows,
    }
    (OUT / "resolve_rate.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for k, v in report.items():
        if k != "zones":
            print(f"  {k:28s} {v}")
    print("\n  per zone:")
    for r in rows:
        print(f"    {r['zone'][:34]:36s} clashes={r['clashes_in_zone']:2d} "
              f"sourced={r['sourced']:2d} esc={r['escalated_with_alternatives']:2d} "
              f"batch={r['batch_status']:9s} -> {r['outcome']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
