"""Run the kit over any IFC dropped into fixtures/owner_models/.

Exists because the owner's models are Navisworks .nwd, which nothing but
Autodesk software can read. The export is a manual step; this is everything
that happens automatically the moment the exported .ifc lands.

A model with zero MEP elements is REPORTED and skipped, not silently
processed into an empty report -- the same rule that rejected the public
utilities model.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.blocks.bcf_export import export_bcf
from app.blocks.clash_resolver import STATUS_PROPOSED, resolve, verify_batch
from app.blocks.clash_triage import triage
from app.blocks.clearance_rules import load_rules
from app.blocks.geometry_engine import aabb_overlaps, judge_pair
from app.blocks.ifc_loader import load_elements, model_sha256, zone_key
from app.blocks.model_clone import apply_to_clone

KIT = Path(__file__).parent.parent
DROP = KIT / "fixtures" / "owner_models"
CLEARANCE_M = 0.3


def run_one(ifc: Path, rule) -> dict:
    t0 = time.time()
    sha_before = model_sha256(ifc)
    els = list(load_elements(ifc, include_structural=True))
    for e in els:
        e.zone_key = zone_key(e)
    mep = [e for e in els if e.discipline == "mep"]

    if not mep:
        return {
            "model": ifc.name,
            "skipped": True,
            "reason": (
                "zero MEP elements — not a coordination model. Check the "
                "Navisworks export included the services, not just architecture."
            ),
            "elements": len(els),
            "runtime_s": round(time.time() - t0, 1),
        }

    findings = []
    admitted = 0
    for a in mep:
        for b in els:
            if a.global_id == b.global_id:
                continue
            if not aabb_overlaps(a.bbox, b.bbox, pad=CLEARANCE_M):
                continue
            admitted += 1
            findings.append(judge_pair(
                a.global_id, b.global_id, a.mesh, b.mesh,
                required_clearance_m=CLEARANCE_M,
                rule_id=getattr(rule, "rule_id", None),
                category_a=a.system, category_b=b.system,
            ))

    by_id = {e.global_id: e for e in els}
    res = triage(findings, by_id)

    proposals, batches = [], []
    for zk in list(dict.fromkeys(q.zone_key for q in res.queue))[:10]:
        zone_items = [q for q in res.queue if q.zone_key == zk][:8]
        zone_els = [e for e in els if e.zone_key == zk]
        zprops = []
        for item in zone_items:
            el = by_id.get(item.element_a)
            if el is None:
                continue
            neigh = [e for e in els if e.global_id != el.global_id
                     and aabb_overlaps(el.bbox, e.bbox, pad=2.0)]
            zprops.append(resolve(
                item, el, neigh, required_gap_mm=CLEARANCE_M * 1000,
                rule_ids=[rule.rule_id] if rule else [],
                clause_text=getattr(rule.source, "clause", None) if rule else None,
            ))
        if zprops:
            batches.append(verify_batch(zprops, by_id, zone_els,
                                        CLEARANCE_M * 1000, zone_key=zk))
            proposals.extend(zprops)

    clone = apply_to_clone(ifc, proposals, KIT / "acceptance_out" / ifc.stem)
    bcf = KIT / "acceptance_out" / ifc.stem / "issues.bcfzip"
    try:
        export_bcf([f for f in findings if f.kind in ("clash", "clearance")][:200],
                   bcf, ifc.stem)
        bcf_ok = bcf.exists()
    except Exception:  # noqa: BLE001 -- report it, do not fail the whole run
        bcf_ok = False

    sha_after = model_sha256(ifc)
    return {
        "model": ifc.name,
        "skipped": False,
        "mb": round(ifc.stat().st_size / 1e6, 1),
        "elements": len(els),
        "mep_elements": len(mep),
        "pairs_admitted": admitted,
        "hard_clashes": sum(1 for f in findings if f.kind == "clash"),
        "clearance_violations": sum(1 for f in findings if f.kind == "clearance"),
        "false_positives_eliminated": sum(1 for f in findings if f.kind == "clear"),
        "queued": len(res.queue),
        "zones_attempted": len(batches),
        "batches_accepted": sum(1 for b in batches if b.status == "accepted"),
        "batches_rejected": sum(1 for b in batches if b.status == "rejected"),
        "proposals": len(proposals),
        "sourced": sum(1 for p in proposals if p.status == STATUS_PROPOSED),
        "bcf_written": bcf_ok,
        "clone_backend": clone.backend,
        "original_untouched": sha_before == sha_after,
        "runtime_s": round(time.time() - t0, 1),
    }


def main() -> int:
    DROP.mkdir(parents=True, exist_ok=True)
    models = sorted(DROP.glob("*.ifc"))
    if not models:
        print(f"No .ifc found in {DROP}")
        print("Export from Navisworks: File > Export > IFC, then drop the file here.")
        print("See the README in that folder.")
        return 0

    rules = load_rules(KIT / "bundle" / "app" / "blocks" / "seed_rules.json")
    rule = next(iter(rules), None)

    rows = [run_one(m, rule) for m in models]
    out = KIT / "acceptance_out" / "OWNER_MODELS.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    for r in rows:
        print(json.dumps(r, indent=2))
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
