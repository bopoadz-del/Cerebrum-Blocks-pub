# MEP Coordination — Clash Judge

Finds true clashes and clearance violations between MEP services (and MEP vs.
structure) in an IFC model, triages them into a queue an engineer will
actually work, proposes checked and sourced resolutions, and hands off a BCF
issue package plus a change set. The original model is never written to.

This document covers inputs, outputs, the rule table format, and — the part
most clash tools skip — the honest limits of what this kit can and cannot
prove.

## Inputs

**Accepted:** IFC4 and IFC2X3 model files only. That is the whole list.

Everything else is out of scope, by design, not by omission:

- **Revit (.rvt)** — Revit (.rvt) is Autodesk-proprietary. Export from Revit
  as IFC (File > Export > IFC, IFC 4 or IFC 2x3) and upload the .ifc file.
- **Navisworks (.nwd / .nwc)** — same instruction: these are Autodesk-
  proprietary aggregation formats, not an interchange schema this kit parses.
  Export the constituent models to IFC and upload those.

No block in this kit attempts to read .rvt, .nwd, or .nwc directly, and none
ever will without first landing IFC support for whatever replaces the
export step above — see the `NEVER` clause in `kit.json`.

Optional inputs:

- A clearance rule table (JSON; see **Rule table format** below). Ships with
  three seeded, sourced rules in `seed_rules.json` — see
  `seed_rules.README.md` for exactly where each one came from.
- A programme CSV of `(zone, planned_install_date)` rows, used to rank the
  triage queue by installation urgency. Its absence is not an error:
  congestion alone drives ranking when no programme is supplied.
- `SPECKLE_SERVER` / `SPECKLE_TOKEN` environment variables, for the Speckle
  clone path (see **Limits** below).

## Outputs

- **Findings** — one record per judged element pair: `clash`, `clearance`,
  `clear`, or `unjudged`, each carrying the method that judged it
  (`exact_boolean`, `surface_intersection`, `min_distance`, or `no_geometry`)
  and, for a clearance verdict, the `rule_id` and clause it was measured
  against. A hard clash cites no rule, deliberately: interpenetrating solids
  are a clash under any rule.
- **Prioritised queue** — findings deduplicated on the unordered
  `(system pair, element pair, zone)` key, workflow noise (a fitting
  overlapping the segment it joins) dropped and counted (never silently),
  and ordered by resolution stage (`order.yaml`), then programme date, then
  zone congestion, then severity in millimetres.
- **BCF 2.1 zip** (`.bcfzip`) — one issue folder per exportable finding
  (`clash` / `clearance` only; `clear` and `unjudged` are not issues), each
  with a `markup.bcf` and, when the finding carries a centroid, a
  `viewpoint.bcfv` with a camera. No centroid means no camera element at
  all — never a camera pointed at a made-up location. Validated structurally
  on every write (`validate_bcf_zip`): a `bcf.version` declaring `2.1`, and
  every issue folder holding its `markup.bcf`.
- **change_set.json** — every proposed move, in the form an engineer applies
  by hand in their authoring tool: `{clash_id, element_global_id,
  move_vector_mm, rule_ids, clause_text, status, note}`. `status` is one of
  `proposed`, `flagged_unsourced`, or `escalated` — never silently omitted.
- **A clone**, never the original — a modified IFC copy beside the original
  (always produced), or a Speckle commit when configured (see **Limits**).
  A `.proposals.json` sidecar rides beside the clone; proposed moves are
  never baked into the IFC geometry itself, because a half-correct
  placement rewrite outside an authoring tool produces a model that opens
  but is subtly wrong.

## Rule table format, and the citation requirement

A clearance rule is a JSON object (see `clearance_rule.schema.json` for the
full schema):

```json
{
  "rule_id": "MEP-GAS-ANY-300",
  "system_a": "gas_main",
  "system_b": "*",
  "min_gap_mm": 300,
  "axis": "any",
  "source": {
    "doc": "PROJECT-UTILITIES-DRAWING-001",
    "clause": "NOTES item 6",
    "text_hash": "2d085ef2123b39a9"
  },
  "precedence": "project_spec"
}
```

**The core invariant: a rule without a clause is not a rule.** `load_rules()`
refuses — by raising `RuleWithoutCitation`, immediately, naming the
`rule_id` — any rule missing `source.clause` or `source.text_hash`. It does
not warn and continue, and it does not drop the rule silently and keep
going: either behaviour would let a coordination pass look complete while
quietly missing an input someone forgot to source. Nothing in this kit
invents a clearance value or a citation, and no rule is added to
`seed_rules.json` without a real, retrieved citation.

`system_a` / `system_b` may be the wildcard `*`. Matching is unordered — a
rule for `(a, b)` also matches a finding reported as `(b, a)`. When two
rules govern the same pair, `resolve_precedence()` lets a `project_spec`
rule win **only when it is stricter** (larger `min_gap_mm`) than the `code`
rule it would replace; a looser project rule never overrides a code minimum,
because a code minimum is a legal floor a project has no authority to lower.

## Limits — stated because an overstated clash engine is worse than none

- **The bounding-box (AABB) check is a pre-filter only, never a verdict.**
  It exists to cheaply discard pairs that provably cannot touch. It is
  padded by the largest clearance rule in play (see `aabb_overlaps(pad=...)`
  in `geometry_engine.py`) — without that pad, the pre-filter would discard
  exactly the near-miss pairs the clearance check exists to find. Every pair
  the AABB admits is then judged on real triangle meshes; the AABB itself
  never produces a clash or clearance finding.
- **Exact penetration depth needs `manifold3d` and a watertight mesh.**
  Without both, contact is still *proven* (via surface intersection or
  measured separation) but the *depth* of an interpenetration is not
  measurable. Every finding records which method judged it —
  `exact_boolean` (penetration volume measured), `surface_intersection`
  (contact proven, depth unknown), or `min_distance` (no touch, separation
  measured) — so a consumer ranking by severity always knows which kind of
  evidence it is looking at, and never has to assume.
- **An element with no geometry is reported `unjudged`, never `clear`.**
  IfcOpenShell must produce a mesh for both sides of a pair (annotations,
  spaces, and some proxies often will not). Silence is not a pass: a pair
  that could not be judged is reported as unjudged, with a note, and is
  excluded from `clearance_rules.evaluate()` (which needs a real distance)
  and from `version_diff`'s "resolved"/"new" reasoning (an unjudged pair
  never counts as proof of "clear").
- **`IfcSystem` is absent from IFC2X3 models of this vintage.** Measured on
  the reference fixture (`schependomlaan_design.ifc`, IFC2X3, 47 MB): zero
  `IfcSystem` entities. Rather than report every MEP element's system as
  "unknown," `ifc_loader.py` **infers** system membership from entity type
  and name (Dutch name fragments included — the fixture is a Dutch project
  and reads e.g. `hwa afvoer` for storm drainage), and every `Element`
  carries `system_source` recording how: `"name_hint"` (matched a keyword),
  `"type_default"` (fell back to the IFC entity type), or `"unknown"`
  (neither matched). A guess that announces itself as a guess is auditable;
  a guess wearing the same label as a fact is not. When a model *does* carry
  real `IfcSystem` / `IfcDistributionSystem` relationships, wiring that path
  in is future work — it is not read today, and nothing here claims it is.
- **Speckle needs both `SPECKLE_SERVER` and `SPECKLE_TOKEN`.** `specklepy`
  must also be importable. Without either condition, `model_clone` does not
  fail — it falls back to the IFC-copy path (always available) and records
  a `blocked` line naming the specific unblocker (missing library vs.
  missing server/token are reported separately, because they have different
  fixes). The IFC-copy path is what runs today on a default install.
- **The original model is never written — hash-asserted, not just
  promised.** `apply_to_clone()` hashes the original file (`model_sha256`)
  before and after every run and raises `RuntimeError` if the two hashes
  differ, regardless of which backend (Speckle or IFC-copy) was used. This
  is the one invariant this kit treats as non-negotiable: a coordination
  agent that can silently edit the drawing of record is not a tool an
  engineer can accept, however good its geometry. Proposed moves live in
  `change_set.json` and a `.proposals.json` sidecar for the engineer to
  apply themselves, in their own authoring tool, where placement
  relationships are maintained correctly.

## Blocks in this kit

| block | module | reads | writes |
|---|---|---|---|
| `geometry_engine` | `app.blocks.geometry_engine` | IFC meshes, element pairs, a clearance requirement | one `Finding` per pair |
| `clearance_rules` | `app.blocks.clearance_rules` | a rule source (JSON path or list), findings | `Violation` list |
| `clash_triage` | `app.blocks.clash_triage` | findings, element metadata, optional programme CSV | prioritised `QueueItem` list |
| `clash_resolver` | `app.blocks.clash_resolver` | a queue item, an element, its neighbours, a rule | a `Proposal` (proposed / flagged / escalated) |
| `bcf_export` | `app.blocks.bcf_export` | clash/clearance findings | a validated `.bcfzip` |
| `version_diff` | `app.blocks.version_diff` | two findings lists from separate runs | resolved / new / regressed / persisting buckets |
| `model_clone` | `app.blocks.model_clone` | the original IFC, proposals | `change_set.json` + a clone (never the original) |

`ifc_loader` (`app.blocks.ifc_loader`) is a helper, not a block: it turns an
IFC file into the meshed `Element` objects the blocks above consume. It is
listed in `kit.json` under `helpers`, not `blocks`.

See `kit.json` for the machine-readable action map, and
`routing/golden_matrix.json` for the utterances this kit is expected (and
expected *not*) to route on.

---

## Joint filter — PROVISIONAL calibration

> **Status: PROVISIONAL.** The threshold below was calibrated on two fixtures,
> **neither of which carries any port connectivity data**. It is the best answer
> available from the evidence to hand, and it is explicitly not yet confirmed
> against a production model. Treat it as a working value, not a settled one.

### What the filter decides

Whether two touching elements are a **joint** (segments that meet by design —
assembly, not conflict) or a **real clash**.

Two signals, in order of authority:

1. **Topology.** Elements whose `IfcDistributionPort`s are linked by
   `IfcRelConnectsPorts`, or joined by a fitting via `IfcRelNests`, are
   connected because *the model says so*. This is evidence, and it wins
   outright wherever it exists.
2. **Measured volume fraction.** Where the model carries no ports, the shared
   volume as a **fraction of the smaller element** separates the two cases.
   This is exact geometry, not a proximity guess.

### The calibration set — 24 + 1

| | source | shared volume | fraction of smaller element |
|---|---|---|---|
| 24 joints | every touching pair in `Infra-Plumbing.ifc` (real fixture) | 4.2×10⁻¹⁷ … 1.6×10⁻⁸ m³ | **< 10⁻⁶** |
| 1 real crossing | constructed pipe-through-pipe, same system, no port link | 5.2×10⁻³ m³ | **0.0844** |

The band between them is empty by roughly five orders of magnitude — a real
conflict measures about **84,000×** the joint ceiling. The threshold
(`TOUCH_VOLUME_FRACTION = 1e-4`) sits inside that gap: ~100× above the worst
observed joint, ~800× below the smallest observed real overlap.

### Why a fraction and not an absolute volume

An absolute floor was tried **first and rejected**. At 10⁻⁹ m³ it excluded only
**3 of 24** joints, because triangulated cylinders that merely touch still
enclose a small faceting volume, and that volume **scales with pipe diameter**.
An absolute floor therefore cannot tell a 50 mm pipe's joint from a 2 m
culvert's real overlap. A fraction is scale-invariant and means the same thing
at both sizes.

### Why it is provisional

The calibration set has three weaknesses, all of them stated rather than
discovered later:

- **One real source.** 24 of the 25 data points come from a single 26-element
  drainage model. Its pipes are one diameter, one material, one export tool.
- **One synthetic counter-example.** The "real crossing" is constructed. It is
  unambiguous, but it is not a conflict anyone actually built.
- **No port data anywhere.** The topology path — the signal that should
  normally decide this — has never run against a model that exercises it.
  Its tests use a synthetic graph.

A model from a different authoring tool, at a different mesh resolution, or
with genuinely shallow real conflicts, could land inside the gap.

### Re-calibration on the first production model

The watcher on `fixtures/owner_models/` runs the full pipeline on the first
exported IFC that appears. Its first row **includes a re-calibration table
before any verdict is reported**:

- the observed joint volume-fraction distribution (min / median / p90 / max)
- the observed real-clash distribution
- whether the empty band still exists, and where its edges now sit
- whether `IfcRelConnectsPorts` is present — if it is, topology decides and the
  fraction becomes a fallback that should rarely fire

If the band has closed, the verdict is withheld and the threshold is re-derived
from the production data. A number calibrated on two toy models must not be
allowed to quietly become a fact about a real building.
