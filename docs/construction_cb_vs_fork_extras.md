# Construction: Cerebrum-Blocks (CB) vs The_Fork — Extra Features Report

Comparison date: 2026-06-10  
Primary files compared:

| File | CB | Fork |
|------|----|------|
| `app/containers/construction.py` | 8,019 lines | 7,329 lines |
| `app/blocks/construction_v2.py` | 497 lines | 520 lines |

Both containers declare **version `3.1`**. Both v2 blocks declare **version `2.0`**.

CB’s container is **+690 lines** (~9.4% larger). Fork’s v2 block is **+23 lines** (~4.6% larger) because it adds knowledge/confidence plumbing CB lacks.

---

## Executive summary

**CB’s extras** cluster around production hardening (safe parsing, logging, audit fixes), richer native parsers (Excel schedules, inline RSMeans), SPA-oriented pipeline behavior, and two unique actions (`discover_projects`, `merge_drawings`).

**Fork’s extras** cluster around modular block delegation (`_resolve_block`, `document_engine`), conversational EVM chat, generative WBS/CPM, shared `construction_*` core modules, and smarter v2 analysis (document-type routing, `ConstructionKnowledge`, confidence scoring).

Neither tree is a strict superset of the other.

---

## 1. Line counts & version strings

| Artifact | CB lines | Fork lines | Version |
|----------|----------|------------|---------|
| `containers/construction.py` | 8,019 | 7,329 | 3.1 / 3.1 |
| `app/blocks/construction_v2.py` | 497 | 520 | 2.0 / 2.0 |
| CB function count (container) | 287 | 263 | — |
| CB function count (v2) | 20 | 20 | — |

---

## 2. CB-only functions (container)

39 functions exist in CB but not in Fork (selected by category):

### Safety / parsing helpers (module-level)
- `_safe_float` — tolerant numeric coercion (43 call sites)
- `_parse_money_str` — US/EU money string heuristics
- `_safe_iso_date` — multi-format date parsing without crashes

### Schedule / Excel
- `_xlsx_match_alias`, `_xlsx_classify_header_row`, `_xlsx_has_schedule_sheet`
- `_parse_xlsx_schedule`, `_normalise_date`

### Project discovery & drawings
- `discover_projects` — cluster uploaded files into projects (zvec + fallback)
- `merge_drawings` — stitch adjacent DXF sheets via `drawing_qto`

### RFI automation
- `_auto_detect_rfi_items`, `_map_rfi_discipline`, `_add_days`

### BIM clash (inline implementation)
- `_detect_model_clashes`, `_detect_internal_clashes`
- `_categorize_clash_severity`, `_prioritize_clash_resolution`
- `_generate_clash_resolution_actions`, `_suggest_clash_resolution`

### Cost / spec (inline data & extraction)
- `_get_rsmeans_data`, `_lookup_unit_cost` (large embedded rate book)
- `_process_spec_from_text`, `_extract_materials`, `_extract_methods`
- `_extract_testing_requirements`, `_extract_qaqc`

### Routing / ops
- `_status` — introspect available actions via `route("__list__", …)`
- `safe_float` (alias/wrapper in some code paths)

Fork implements overlapping behavior by **delegating to blocks** (`bim_extractor`, `historical_benchmark`, `document_engine`, `spec_analyzer`) rather than inlining.

---

## 3. CB-only helpers & audit fixes

| Helper | Purpose | Fork equivalent |
|--------|---------|-----------------|
| `_safe_float` | Prevents `ValueError` on `"10%"`, `"1,200"`, `None` in params | Direct `float()` / block-level handling |
| `_parse_money_str` | Parses ambiguous `1.234.567,89` vs `1,234,567.89` | Not present |
| `_safe_iso_date` | Tolerates Primavera/non-ISO date strings | `_parse_event_date` (Fork-only, narrower) |
| `logger` (16 uses) | `warning` on bad XER rows; `debug` on xlsx classify failures | No module logger |
| `pipeline_warnings` | Per-panel failure list for SPA (“1 panel failed to populate”) | Not present |
| `_qty_val` | Quantity normalization via `_safe_float` in `auto_pipeline` | Simpler quantity handling |
| `known_actions` in `route()` errors | Returns sorted action list on unknown action | Error message only, no action list |

Comments in CB explicitly reference **audit findings** (unsafe `float()`, `datetime.fromisoformat()` crashes, duplicate `route()` stub removed).

---

## 4. CB-only actions & routing

### Registered in `get_actions()` / `route()` — CB only
| Action | Description |
|--------|-------------|
| `discover_projects` | Group file lists into projects (path prefix + zvec similarity) |
| `merge_drawings` | Multi-DXF continuity / sheet stitching |

### Route aliases (CB only — backward compatibility)
| Alias | Maps to |
|-------|---------|
| `cost_estimate` | `generate_cost_estimate` |
| `analyze_spec` | `analyze_spec_section` |
| `schedule_risk` | `analyze_schedule_risk` |
| `contract_review` | `process_contract` |
| `safety_audit` | `safety_compliance_audit` |
| `carbon_report` | `generate_carbon_report` |
| `procurement` | `procurement_analysis` |
| `status` | `_status` |

### `construction_v2` CB-only behavior
- Early `status` / `health` return in `process()` when `params.action` requests it
- `_calculate_quantities(measurements, params)` — **requires explicit** `slab_thickness_m`, `steel_density_kg_m3`, `rebar_density_m_m3`; emits `_note` when missing (no fabricated defaults)
- Local `@dataclass` definitions (`Measurement`, `SpecItem`, `RiskItem`) inlined in the block file

---

## 5. CB extras by category

### Safety & robustness
- Module-level safe parsers (`_safe_float`, `_parse_money_str`, `_safe_iso_date`)
- Structured logging on schedule parse edge cases
- Panel-level `pipeline_warnings` in `auto_pipeline` for SPA error surfacing
- XER row skip with warning instead of aborting whole parse

### Parsing & document handling
- **Native Excel schedule parser** — header alias matching, sheet detection, CPM input from `.xlsx`/`.xls`
- Document classify pre-check: xlsx files with schedule headers → `schedule` type
- Inline spec text extraction helpers (materials, methods, QA/QC, testing)

### Actions & integrations
- `discover_projects` — drive-connect project grouping
- `merge_drawings` — cross-sheet DXF alignment
- Legacy route aliases + `status` introspection action
- `known_actions` hint on routing errors

### Cost & quantities
- Embedded **RSMeans-style rate book** (`_get_rsmeans_data`, ~170 lines of unit costs + regional multipliers)
- `auto_pipeline` building-type GFA rates (`BUILDING_TYPE_RATES_USD`) and currency conversion table
- Fork **removed** the hardcoded rate book; cost estimate fails without `historical_benchmark` block data

### RFI & workflow
- Auto-detect RFI candidates from `extracted_text` (TBD/TBC/clarification/missing dimension patterns)
- Richer inline BIM clash scenario modeling (Fork delegates clash to `bim_extractor`)

### Code hygiene
- Duplicate `route()` stub removed (documented in-file)
- `historical_benchmark` still listed in `requires` (Fork comment: removed in favor of `learning_engine`)

---

## 6. Fork-only features (balance — CB lacks these)

### Container actions
| Action | Description |
|--------|-------------|
| `chat` | EVM-anchored conversational turn via `ChatBlock` + `construction_evm.md` prompt |
| `generate_wbs` | Template-based WBS + CPM from project brief (20–1000 activities) |

### Architecture / delegation
- `_resolve_block`, `_get_*_block` helpers — uniform block lookup
- `_process_office_document` — routes `.docx`/`.xlsx` through `document_engine` + `boq_processor`
- BIM clash via `bim_extractor` with `run_clash_detection=True` (real block path vs CB demo scenarios)
- Cost estimate via `historical_benchmark` lookup with honest `unpriced_items` when no rate exists

### `construction_v2` (Fork ahead)
- `ConstructionKnowledge` + `enforce_critical_rules()` on contracts
- `assess_extraction_confidence()` → `confidence_report` per analysis type
- Extended `_detect_document_type`: `ncr`, `rfi`, `payment`, `change_order`, `design_review`, `risk`
- Shared types from `app.core.construction_types`
- Hardcoded quantity defaults (150 mm slab, 120 kg/m³ steel) when params omitted

### Core modules (Fork `app/core/`, absent in CB main app)
- `construction_knowledge.py`
- `construction_types.py`
- `construction_constants.py`

### Tests & docs (Fork only)
- `tests/test_construction_chat.py`
- `tests/test_construction_kb.py`
- `tests/test_construction_generate_wbs.py`
- `docs/knowledge/construction_kb.md`
- `.claude/agents/construction-expert.md`, `app/agents/configs/construction-pm.md`

---

## 7. Tracked construction files — CB vs Fork

### Present in both repos
- `app/containers/construction.py`
- `app/blocks/construction_v2.py`
- `app/prompts/construction_expert.txt`
- `app/prompts/construction_evm.md`
- `app/knowledge/construction_kb.json`

### CB-only tracked files
| Path | Notes |
|------|-------|
| `app/blocks/container_construction.py` | Alternate `ContainerBlock` wrapper (v3.2.0) |
| `scripts/publish_construction_kit.py` | Kit publishing automation |
| `tests/test_regression_construction.py` | Regression suite |
| `block_store/kits/construction/bundle/**` | Packaged kit including `construction_knowledge.py`, `construction_types.py`, `construction_constants.py` (in bundle, not main `app/core/`) |

### Fork-only tracked files
| Path | Notes |
|------|-------|
| `app/core/construction_knowledge.py` | Live in main app |
| `app/core/construction_types.py` | Shared dataclasses |
| `app/core/construction_constants.py` | Shared constants |
| `tests/test_construction_chat.py` | Chat action tests |
| `tests/test_construction_kb.py` | Knowledge base tests |
| `tests/test_construction_generate_wbs.py` | WBS generator tests |
| `docs/knowledge/construction_kb.md` | KB documentation |
| Agent config markdown files | construction-expert, construction-pm |

**Note:** CB carries `construction_knowledge` inside the **block_store kit bundle**, not as first-class `app/core/` modules. Fork promotes those modules to `app/core/` and wires them into `construction_v2`.

---

## 8. `construction_v2` side-by-side

| Capability | CB | Fork |
|------------|----|------|
| Function names | Same 20 methods | Same 20 methods |
| `status`/`health` shortcut | Yes | No |
| Quantity calculation | Param-driven, no silent defaults | 150 mm slab / 120 kg/m³ defaults |
| Confidence scoring | Static per analysis type | `assess_extraction_confidence` + report |
| Contract rules | Regex clauses only | `ConstructionKnowledge.enforce_critical_rules` |
| Document auto-detect | drawing/spec/contract/schedule/generic | + ncr, rfi, payment, change_order, design_review, risk |
| Type definitions | In-file dataclasses | `app.core.construction_types` |

---

## 9. Recommendation snapshot

| If you need… | Prefer |
|--------------|--------|
| Safe param parsing in the field | **CB** container |
| Excel schedule ingest without extra blocks | **CB** container |
| Offline cost estimates without benchmark DB | **CB** (`_get_rsmeans_data`) |
| Project file clustering / DXF merge | **CB** actions |
| EVM chat + WBS generation | **Fork** |
| Knowledge-base rule enforcement in v2 | **Fork** |
| Honest “unpriced item” cost estimates | **Fork** (benchmark block) |
| Office doc (.docx/.xlsx) via document engine | **Fork** |

---

*Generated by diffing `Cerebrum-Blocks` vs `The_Fork` construction container and v2 block sources.*
