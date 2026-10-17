# MEP Coordination — Clash Judge

Takes an IFC model, finds true clashes and clearance violations in MEP
services (and MEP vs. structure), triages them into a queue an engineer will
actually work, proposes checked and sourced resolutions on a clone, and
tracks whether a re-run actually fixed what it targeted. The original model
is never written to. See `docs/MEP_KIT.md` for inputs, outputs, the rule
table format, and the kit's honest limits.

## Blocks

| # | Block | Entry point | Does |
|---|-------|-------------|------|
| B1 | `geometry_engine` | `judge_pair` | Exact clash/clearance judgement from real triangle meshes; AABB is a pre-filter only, never the verdict. |
| B2 | `clearance_rules` | `evaluate` | Sourced minimum-gap rules. A rule missing `source.clause`/`source.text_hash` is refused at load, never silently dropped. |
| B3 | `clash_triage` | `triage` | Dedupes, drops workflow noise (counted, never silent), and ranks findings into a queue, per `order.yaml`. |
| B4 | `clash_resolver` | `resolve` | Proposes a re-checked, sourced move for one queued clash, or flags/escalates it. No LLM in the decision path; gravity services keep their fall. |
| B5 | `bcf_export` | `export_bcf` | Writes a validated BCF 2.1 package for hand-off to Navisworks/Solibri/BIMcollab. |
| B6 | `model_clone` | `apply_to_clone` | Writes `change_set.json` and a modified IFC/Speckle clone. The original file is hash-identical before and after. |
| B7 | `version_diff` | `diff_versions` | Compares two runs on the unordered element-pair key and buckets outcomes into resolved / new / regressed / persisting; scores proposals against what actually resolved. |

`identity.py` is a shared (non-block) module: the single canonical
`element_key` / `pair_key` / `clash_id` derivation that B3 and B7 both use,
so they can never again derive "the same" clash id two different ways — see
`bundle/tests/test_identity.py`.

## Fixture

**Source:** `https://github.com/openBIMstandards/Archive-DataSetSchependomlaan`
(archived repo).
**Path in that repo:** `Design model IFC/IFC Schependomlaan.ifc`
**sha256:** `2c3565ca1904f2aa61adab92024cf3755b2c5b21a498144d3094d7cb58cebec7`
**Size / schema:** 47 MB, IFC2X3, 73 MEP elements, 2954 structural elements,
6 storeys.

**Why the archived repo, not the live one:** both the order's URL and the
live `openBIMstandards/DataSetSchependomlaan` repo point at paths that 404.
The live repo is now only a README forwarding to a location that no longer
exists — the archived repo is the only place the actual file still lives.

**The companion `HB_Nutsvoorzieningen.ifc` is NOT used.** It has 0 MEP
elements (45 products, all non-MEP), and the order's own rule is explicit:
zero MEP elements in a fixture is not a fixture. It was deleted rather than
kept as decoration — see `fixtures/FIXTURES.md` for the full accounting of
what was considered and rejected.

**Fetching it:** run `fixtures/fetch_fixtures.sh`. The `.ifc` file is
gitignored (47 MB) — nothing under `fixtures/` other than the fetch script
and `FIXTURES.md` is committed.

## Tests

`bundle/tests/` covers every block in isolation (constructed geometry, no
IFC file needed for anything except `ifc_loader` itself) plus
`test_cross_block_integration.py`, which runs the real
B1 → B3 → B4 → B7 pipeline end to end and asserts a proposed fix is actually
recognised as resolved — the permanent regression test for the "green
units, silent zero" class of bug described in `identity.py`.

```
cd bundle
PYTHONPATH=. <python> -m pytest tests/ -q -p no:cacheprovider --rootdir=. -c /dev/null
```
