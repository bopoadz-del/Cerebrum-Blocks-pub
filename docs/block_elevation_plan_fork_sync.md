# Block Elevation Plan — Fork Sync Addendum

**Status:** Active (2026-06-10)  
**Supersedes:** Bulk rewrite assumptions in [block_elevation_plan.md](./block_elevation_plan.md)  
**Source of truth for implementations:** `C:\Users\<owner>\The_Fork` (production Fork)

---

## Executive summary

Cerebrum-Blocks (CB) already has **75/75 registry manifests passing** `audit_block_standards.py`. Most runtime gaps are **stale or slimmed `app/blocks/` copies**, not missing store infrastructure.

**Revised strategy:** bulk-sync `app/blocks/*.py` from The Fork for shared blocks, run `scripts/publish_construction_kit.py` for domain kit sources, and reserve manual elevation for **~10 CB-specific items** (store-only blocks, registry orphans, adapter renames, TypedBlock merges).

| Inventory | Count | Notes |
|-----------|------:|-------|
| The Fork `app/blocks/*.py` (excl `_*.py`) | **45** | Production implementations |
| CB `app/blocks/*.py` (excl `_*.py`) | **85** | Includes 34 store-only + 7 `container_*` helpers + orphans |
| CB `block_registry/` (with `block.json`) | **75** | Audit: 0 errors, 0 warnings |
| Shared filenames (Fork ∩ CB) | **40** | Direct copy/compare candidates |
| Fork-only (missing in CB `app/blocks/`) | **5** | See promotion list below |
| CB-only (no Fork counterpart) | **45** | Store platform blocks — keep CB implementations |

**Audit (2026-06-10):**

```
python scripts/audit_block_standards.py
Blocks scanned: 75
Blocks with errors: 0
Blocks with warnings: 0
```

---

## Category A — Safe to copy from Fork (bulk sync)

Copy `The_Fork/app/blocks/{name}.py` → `Cerebrum-Blocks/app/blocks/{name}.py`, then regenerate adapters only if inputs/widgets drift:

| Block | Fork vs CB | Action |
|-------|------------|--------|
| `cache_manager` | Identical | Copy (no-op) |
| `voice` | ~identical | Copy |
| `async_processor` | Fork ≥ CB | Copy |
| `file_hasher` | Fork ≥ CB | Copy |
| `android_drive` | Fork ≥ CB | Copy |
| `translate` | Fork ≥ CB | Copy |
| `vector_search` | Fork ≥ CB | Copy |
| `web` | Fork ≥ CB | Copy |
| `webhook` | Fork ≥ CB | Copy |
| `pdf_v2` | Fork ≥ CB | Copy |
| `search` | Fork ≥ CB | Copy |
| `zvec` | Fork larger | Copy |
| `ocr` | Fork larger (374 vs 283 LOC) | Copy |
| `image` | Fork larger (452 vs 286) | Copy |
| `local_drive` | Fork larger | Copy |
| `google_drive` | Fork larger | Copy |
| `ocr_v2` | Moderate drift | Copy, smoke-test |

**Virgin 17 blocks that are Fork-ahead but need a post-copy pass (not raw paste-only):** see Category C (`chat`, `document_engine`, `pdf`, `code`, `orchestrator`).

**Fork-only files to add to CB `app/blocks/`:**

| File | Notes |
|------|-------|
| `formula_executor_v2.py` | In kit bundle only today — promote to `app/blocks/` + registry |
| `project_reasoner.py` | Same |
| `validation_pipeline.py` | Fork virgin id; CB uses `validation` — map, do not blind rename |
| `mcp_adapter.py` | Extended boot only; optional for CB legacy boot |
| `mcp_consumer.py` | Extended boot only; optional for CB legacy boot |

---

## Category B — CB-only / store-only (keep CB implementations)

No Fork `app/blocks/{name}.py` counterpart. Registry manifests already pass audit; elevation = tests + domain-boundary review, **not** Fork copy.

`adaptive_router`, `agent_swarm`, `analytics`, `audit`, `auth`, `billing`, `capture`, `config`, `context_broker`, `dashboard`, `database`, `discovery`, `documentation`, `email`, `error_tracking`, `event_bus`, `failover`, `health_check`, `historical_benchmark`, `knowledge`, `library_container`, `migration`, `monitoring`, `notification`, `payment_split`, `queue`, `rate_limiter`, `review`, `secrets`, `skills`, `storage`, `team`, `validation`, `vector`, `version`, `workflow`

**Helpers (not registry blocks):** `container_ai_core`, `container_construction`, `container_infrastructure`, `container_platform`, `container_security`, `container_store`, `container_team`, `container_utility`

---

## Category C — ~10 blocks needing real CB-specific work

These cannot be solved by copy/paste alone:

| # | Block | Why CB-specific work remains |
|---|-------|------------------------------|
| 1 | **`memory`** | Full Python impl; **no** `block_registry/`; hard dep of `orchestrator`, `auth`, `vector`, `queue`, etc. |
| 2 | **`sandbox`** | `block_registry/sandbox/block.py` bypasses `BLOCK_REGISTRY` + `execute()` envelope |
| 3 | **`validation`** | CB registry id `validation` vs Fork `validation_pipeline` — adapter + boot spec alignment |
| 4 | **`formula_executor_v2`** | Fork source exists; CB needs `app/blocks/` root + `block_registry/` promotion |
| 5 | **`project_reasoner`** | Same as `formula_executor_v2` |
| 6 | **`orchestrator`** | Blocked until `memory` registry exists; merge Fork runtime + CB dep wiring |
| 7 | **`skills`** | Store-only; construction-coupled strings; no tests |
| 8 | **`container`** | Orphan meta-block vs `DomainContainer` — clarify or deprecate |
| 9 | **`pdf`** | CB TypedBlock + manifest richer than Fork (315 vs 133 LOC) — **merge** Fork logic into CB schemas |
| 10 | **`chat`** | Fork implementation ahead (574 vs 309 LOC) — copy then strip virgin domain leakage (`CONSTRUCTION_KEYWORDS`) |

**Honorable mention (merge, not full rewrite):** `code` (CB TypedBlock/sandbox wiring), `document_engine` (copy Fork + add tests + de-domain manifest), `traffic_manager` (98% similar — copy or trivial sync), `onedrive` (CB slightly larger — review deltas).

---

## Category D — Construction kit (bundle / publish, not platform boot)

Domain blocks ship via `block_store/kits/construction/` and `CEREBRUM_DOMAIN_KITS=construction`. Source is Fork; use **`scripts/publish_construction_kit.py`**, not hand-editing platform tree.

| Block | Fork vs CB drift | Sync path |
|-------|------------------|-----------|
| `construction_v2` | Moderate | Kit publish |
| `boq_processor` | Fork ahead | Kit publish |
| `spec_analyzer` | Fork ahead | Kit publish |
| `sympy_reasoning` | Fork ahead | Kit publish |
| `primavera_parser` | Fork ahead | Kit publish |
| `smart_orchestrator` | Fork ahead | Kit publish |
| `bim` / `bim_extractor` | Fork ahead | Kit publish |
| `learning_engine` | Fork ahead | Kit publish |
| `recommendation_template` | Fork ahead | Kit publish |
| `jetson_gateway` | ~identical | Kit publish |
| `formula_executor` | **CB massively expanded** (574 vs 84 LOC) — review before overwrite |
| `drawing_qto` | CB larger (857 vs 621) — review before overwrite |
| `llm_enhancer` | CB larger — extended-boot block, not kit-only |
| `historical_benchmark` | CB-only in platform registry | Keep CB |

Kit-only today (bundle, not `app/blocks/` root): `formula_executor_v2`, `project_reasoner`, `_procedure_routing.py`

---

## What becomes redundant in the original plan

If Fork sync is the default path, these plan items shrink or disappear:

| Original plan item | Revised approach |
|--------------------|------------------|
| **Tier 2 — reimplement extended/shared blocks** | **Redundant** for any block with a Fork twin — copy + smoke test instead |
| **Tier 3a–3c — rewrite construction blocks** | **Replace** with `publish_construction_kit.py` + spot review (`formula_executor`, `drawing_qto`) |
| **WS-H construction core** | Kit publish workstream (~1–2 d), not ~18 dev-days |
| **Virgin 17 runtime elevation (ocr, image, zvec, …)** | Bulk Fork copy for Category A list |
| **Tier 2 test gaps (~27 blocks)** | Still valid for Category B store-only blocks |
| **Tier 1 blockers** | Still valid — narrowed to Category C (~10) |
| **Grand total ~52 dev-days** | **Revised ~12–15 dev-days** (Category C + Category B tests + kit publish) |

**Keep from original plan:**

- Promote `memory` to full registry (Tier 1)
- Fix `sandbox` adapter pattern (Tier 1)
- Promote `formula_executor_v2` / `project_reasoner` (Tier 1)
- Virgin purity on `chat` post-Fork-copy (Tier 1 / WS-B)
- `validation` ↔ `validation_pipeline` naming ADR (WS-I)
- CI test coverage for Category B store blocks (Tier 2, scoped)

---

## Recommended execution order

1. **Bulk sync (1 d):** Copy Category A files from Fork; `pytest tests/blocks/ -q` + `audit_block_standards.py`
2. **Kit publish (0.5 d):** Run `publish_construction_kit.py` from Fork ref; verify kit install
3. **Category C sprint (5–8 d):** `memory` → `orchestrator` → `sandbox` → kit WIP promotion → `chat` purity → `pdf`/`code` merge
4. **Category B test pass (parallel):** Add smoke tests for store-only blocks missing coverage

### Verification gates (unchanged)

```bash
python scripts/audit_block_standards.py
python scripts/test_block_registry.py {block_id}
pytest tests/blocks/test_{block_id}.py -q
```

---

## Quick reference — copy command pattern

**Bulk platform sync (Category A only):** `scripts/sync_blocks_from_fork.py` copies an explicit allowlist and **skips** all construction kit blocks (`construction_v2`, `boq_processor`, …) plus `app/containers/construction.py` (out of scope — kit publish only). Dry-run first:

```bash
python scripts/sync_blocks_from_fork.py --dry-run
python scripts/sync_blocks_from_fork.py --apply   # after review
```

Single-block manual copy:

```powershell
# Example: sync one block from Fork (run from Cerebrum-Blocks root)
Copy-Item "C:\Users\<owner>\The_Fork\app\blocks\ocr.py" "app\blocks\ocr.py"
python scripts/audit_block_standards.py
python scripts/test_block_registry.py ocr
```

For construction domain blocks, prefer:

```bash
python scripts/publish_construction_kit.py
```

---

*Addendum authored 2026-06-10. Fork path: `C:\Users\<owner>\The_Fork`.*
