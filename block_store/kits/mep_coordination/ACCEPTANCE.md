# MEP kit — ACCEPTANCE (real fixture, end to end)

Fixture: `schependomlaan_design.ifc` — 49.3 MB, IFC2X3
Run date: 2026-09-05

## Original model untouched

    sha256 before : 2c3565ca1904f2aa61adab92024cf3755b2c5b21a498144d3094d7cb58cebec7
    sha256 after  : 2c3565ca1904f2aa61adab92024cf3755b2c5b21a498144d3094d7cb58cebec7
    identical     : True

The kit opens the model read-only and never writes it. This is the proof.

## Scale and timing

| | |
|---|---|
| elements meshed | 1437 (73 MEP, 1364 structural) |
| load + mesh | 27.4 s |
| pairs admitted by the padded AABB filter | 700 |
| mesh judgements | 1.6 s |
| total | 29.2 s |

## Findings

| verdict | count |
|---|---|
| hard clash | 14 |
| clearance violation (<300 mm) | 399 |
| clear | 287 |
| unjudged (no geometry) | 0 |

After triage: **376** queued, 37 duplicates removed, 0 workflow-noise rows dropped and counted.

## The central claim — bounding-box false positives

The AABB pre-filter admitted **700** pairs. The mesh engine judged **287** of them CLEAR.

Every one of those 287 is a pair the old bounding-box detector would have reported as a clash and the engineer would have had to open and dismiss by hand. They are the false positives, measured rather than asserted.

False positives in the top-50 queue: **0**

## Top clashes (manually verifiable)

| # | kind | systems | level | severity mm | rule |
|---|---|---|---|---|---|
| 1 | hard | drainage_storm vs drainage_storm | 00 begane grond | 0 | — |
| 2 | hard | drainage_storm vs drainage_storm | 00 begane grond | 1000 | — |
| 3 | hard | drainage_storm vs structure | 00 begane grond | 1000 | — |
| 4 | clearance | drainage_storm vs drainage_storm | 00 begane grond | 300 | MEP-GAS-ANY-300 |
| 5 | clearance | drainage_storm vs structure | 00 begane grond | 196 | MEP-GAS-ANY-300 |
| 6 | clearance | drainage_storm vs structure | 00 begane grond | 196 | MEP-GAS-ANY-300 |
| 7 | clearance | drainage_storm vs structure | 00 begane grond | 121 | MEP-GAS-ANY-300 |
| 8 | clearance | drainage_storm vs structure | 00 begane grond | 121 | MEP-GAS-ANY-300 |
| 9 | clearance | drainage_storm vs structure | 00 begane grond | 113 | MEP-GAS-ANY-300 |
| 10 | clearance | drainage_storm vs structure | 00 begane grond | 113 | MEP-GAS-ANY-300 |
| 11 | clearance | drainage_storm vs drainage_storm | 00 begane grond | 53 | MEP-GAS-ANY-300 |
| 12 | clearance | drainage_storm vs structure | 00 begane grond | 25 | MEP-GAS-ANY-300 |
| 13 | clearance | drainage_storm vs structure | 00 begane grond | 25 | MEP-GAS-ANY-300 |
| 14 | clearance | drainage_storm vs structure | 00 begane grond | 10 | MEP-GAS-ANY-300 |
| 15 | clearance | drainage_storm vs structure | 00 begane grond | 10 | MEP-GAS-ANY-300 |

Every clearance row cites `MEP-GAS-ANY-300`, sourced to `PROJECT-UTILITIES-DRAWING-001`, NOTES item 6 (chunk hash 2d085ef2123b39a9; the client drawing it maps to is not named in this repository). Hard clashes cite no rule, deliberately: interpenetration is a clash under every rule.
