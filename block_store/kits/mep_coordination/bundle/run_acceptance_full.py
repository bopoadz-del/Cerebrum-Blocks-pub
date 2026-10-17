"""Full acceptance: find -> rule -> triage -> resolve -> clone -> re-run -> diff.

This closes the loop the order asks for. It is not a demo: it applies the
change set to a COPY of the fixture, re-runs detection on that copy, and asks
version_diff whether the clashes the kit said it would fix actually went away.
The kit grades itself and the grade is written down whatever it says.

Every number in ACCEPTANCE.md comes from this run.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.blocks.clash_resolver import STATUS_FLAGGED, STATUS_PROPOSED, resolve, verify_batch
from app.blocks.clash_triage import triage
from app.blocks.clearance_rules import load_rules
from app.blocks.geometry_engine import aabb_overlaps, judge_pair
from app.blocks.ifc_loader import load_elements, model_sha256, zone_key
from app.blocks.model_clone import apply_to_clone
from app.blocks.version_diff import diff_versions, score_proposals

KIT = Path(__file__).parent.parent
FIXTURE = KIT / "fixtures" / "schependomlaan_design.ifc"
OUT = KIT / "acceptance_out"
CLEARANCE_M = 0.3


def detect(elements, clearance_m=CLEARANCE_M):
    """One detection pass. Returns (findings, pairs_admitted_by_boxes)."""
    mep = [e for e in elements if e.discipline == "mep"]
    admitted = 0
    findings = []
    for a in mep:
        for b in elements:
            if a.global_id == b.global_id:
                continue
            if not aabb_overlaps(a.bbox, b.bbox, pad=clearance_m):
                continue
            admitted += 1
            findings.append(judge_pair(
                a.global_id, b.global_id, a.mesh, b.mesh,
                required_clearance_m=clearance_m,
                rule_id="MEP-GAS-ANY-300",
                category_a=a.system, category_b=b.system,
            ))
    return findings, admitted


def main() -> int:
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    sha_before = model_sha256(FIXTURE)

    rules = load_rules(KIT / "bundle" / "app" / "blocks" / "seed_rules.json")
    rule = next((r for r in rules if r.rule_id == "MEP-GAS-ANY-300"), None)
    clause = rule.source.clause if rule else None
    clause_text = getattr(rule.source, "text", None) if rule else None

    els = list(load_elements(FIXTURE, include_structural=True))
    for e in els:
        e.zone_key = zone_key(e)
    by_id = {e.global_id: e}
    by_id = {e.global_id: e for e in els}

    findings_v1, admitted = detect(els)
    res = triage(findings_v1, by_id)

    clear_v1 = [f for f in findings_v1 if f.kind == "clear"]
    active_v1 = [f for f in findings_v1 if f.kind in ("clash", "clearance")]

    # Resolve the top of the queue. Neighbours are the same-zone elements, which
    # is what the resolver re-checks against.
    # SEQUENTIAL, not parallel. Two moves that are each safe against the
    # ORIGINAL model can collide with each other once both are applied -- the
    # first run proved it, producing 25 new clashes from 25 individually
    # "safe" proposals. An engineer applies changes one at a time and sees the
    # model update; the resolver must be checked the same way. Each accepted
    # move is committed to the working state before the next is judged.
    # Per-ZONE batches, verified as a set (item 2). Resolve rate is reported
    # per zone, because a kit that clears open corridors and fails congested
    # ones has a very different value than an average implies.
    proposals = []
    batches = []
    committed: dict[str, tuple] = {}
    for item in res.queue[:25]:
        el = by_id.get(item.element_a)
        if el is None:
            continue
        if el.global_id in committed:
            continue          # this element already has a move; do not stack
        # Neighbours by PROXIMITY, not by zone equality. Zone is a 6 m grid
        # cell, so an element near a cell boundary has most of its real
        # neighbours in the adjacent cell -- checking only its own cell is how
        # the first run produced 26 new clashes from 25 "safe" moves. The
        # order's own wording is "within the zone + 2 m buffer"; proximity is
        # what that means geometrically.
        neighbours = [
            e for e in els
            if e.global_id != el.global_id
            and aabb_overlaps(el.bbox, e.bbox, pad=2.0)
        ]
        prop = resolve(
            item, el, neighbours,
            required_gap_mm=CLEARANCE_M * 1000,
            rule_ids=[rule.rule_id] if rule else [],
            clause_text=(clause_text or clause) if rule else None,
        )
        proposals.append(prop)
        if prop.status == STATUS_PROPOSED:
            # Commit it to the working state so the NEXT proposal is judged
            # against a model that already contains this move.
            el.mesh.apply_translation([v / 1000.0 for v in prop.move_vector_mm])
            el.bbox = tuple(float(x) for x in el.mesh.bounds.flatten())
            committed[el.global_id] = prop.move_vector_mm

    proposed = [p for p in proposals if p.status == STATUS_PROPOSED]
    flagged = [p for p in proposals if p.status == STATUS_FLAGGED]
    escalated = [p for p in proposals if p.status not in (STATUS_PROPOSED, STATUS_FLAGGED)]

    clone = apply_to_clone(FIXTURE, proposals, OUT)

    # --- close the loop: apply the moves to a COPY and re-detect -------------
    applied_copy = OUT / "applied_v2.ifc"
    shutil.copyfile(FIXTURE, applied_copy)
    els_v2 = list(load_elements(applied_copy, include_structural=True))
    for e in els_v2:
        e.zone_key = zone_key(e)
    moved = {p.element: p.move_vector_mm for p in proposed}
    applied = 0
    for e in els_v2:
        v = moved.get(e.global_id)
        if v and e.mesh is not None:
            e.mesh.apply_translation([x / 1000.0 for x in v])
            e.bbox = tuple(float(x) for x in e.mesh.bounds.flatten())
            applied += 1

    findings_v2, _ = detect(els_v2)
    diff = diff_versions(findings_v1, findings_v2)
    score = score_proposals([{"clash_id": p.clash_id} for p in proposed], diff)

    sha_after = model_sha256(FIXTURE)
    total = time.time() - t0

    report = {
        "fixture": FIXTURE.name,
        "fixture_mb": round(FIXTURE.stat().st_size / 1e6, 1),
        "elements": len(els),
        "pairs_admitted_by_boxes": admitted,
        "hard_clashes": sum(1 for f in findings_v1 if f.kind == "clash"),
        "clearance_violations": sum(1 for f in findings_v1 if f.kind == "clearance"),
        "clear_false_positives_eliminated": len(clear_v1),
        "queued": len(res.queue),
        "deduped": res.deduped,
        "workflow_dropped": res.dropped_workflow,
        "proposals_total": len(proposals),
        "proposed_sourced": len(proposed),
        "flagged_unsourced": len(flagged),
        "escalated": len(escalated),
        "moves_applied_to_copy": applied,
        "diff_resolved": len(diff["resolved"]),
        "diff_new": len(diff["new"]),
        "diff_regressed": len(diff["regressed"]),
        "diff_persisting": len(diff["persisting"]),
        "proposal_score": score,
        "clone_backend": clone.backend,
        "clone_blocked": clone.blocked,
        "original_sha_before": sha_before,
        "original_sha_after": sha_after,
        "original_untouched": sha_before == sha_after,
        "runtime_s": round(total, 1),
    }
    (OUT / "acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for k, v in report.items():
        print(f"  {k:34s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
