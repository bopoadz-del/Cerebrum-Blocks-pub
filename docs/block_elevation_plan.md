# Block Elevation Plan

**Status:** Draft (2026-06-10)  
**Goal:** Bring every non-reference block to the same plug-and-play standard as the Virgin Fork 17.  
**Scope:** Plan only — no mass block edits in this document.

---

## Executive summary

The **17 Virgin generic blocks** are the reference tier: they boot by default, have complete `block_registry/` manifests, universal adapters calling `execute()`, typed metadata (`layer`, `tags`, `requires`), and Python `ui_schema` + `process()` implementations.

`scripts/audit_block_standards.py` reports **75/75 registry blocks pass** (0 errors, 0 warnings). Manifest compliance is largely solved. Remaining elevation work is **runtime quality**, **missing registry entries**, **test coverage**, **domain-boundary cleanup**, and **adapter consistency** — not greenfield manifest authoring.

| Inventory | Count |
|-----------|------:|
| Virgin reference blocks | 17 |
| Extended platform (`CEREBRUM_VIRGIN=false`) | 38 |
| Construction kit blocks | 18 |
| Extended v2 duplicates (`pdf_v2`, `ocr_v2`) | 2 |
| Orphan app-only (no `block_registry/`) | 2 (`memory`, `container`) |
| Kit WIP (bundle only, no `app/blocks/` root) | 2 (`formula_executor_v2`, `project_reasoner`) |
| Container helper modules (not blocks) | 7 (`container_*.py`) |
| **Total distinct block implementations** | **~79** |

---

## Audit baseline

**Command run:** `python scripts/audit_block_standards.py`

```
========================================================================
Cerebrum Block Standards Audit
========================================================================
Blocks scanned: 75
Blocks with errors: 0
Blocks with warnings: 0
```

The audit checks `block_registry/{id}/` for: `block.json` required keys, array `ui_schema`, input/widget parity, `block.py` with `run()`, Dockerfile, and docker execution image.

---

## The 17 reference blocks

Source: `app/blocks/__init__.py` → `_GENERIC_BLOCK_DEFS` (docs call this `_GENERIC_BLOCK_SPECS`; registry key is **`validation`**, docs alias **`validation_pipeline`**).

| # | Block | Layer | Base class | Registry | Tests |
|---|-------|------:|------------|----------|-------|
| 1 | `pdf` | 3 | TypedBlock | ✅ full | ✅ |
| 2 | `ocr` | 3 | TypedBlock | ✅ full | ✅ |
| 3 | `image` | 3 | UniversalBlock | ✅ full | ✅ |
| 4 | `document_engine` | 3 | UniversalBlock | ✅ full | ❌ |
| 5 | `chat` | 2 | UniversalBlock | ✅ full | ✅ |
| 6 | `translate` | 3 | UniversalBlock | ✅ full | ✅ |
| 7 | `voice` | 3 | UniversalBlock | ✅ full | ✅ |
| 8 | `web` | 3 | UniversalBlock | ✅ full | ✅ |
| 9 | `search` | 3 | UniversalBlock | ✅ full | ✅ |
| 10 | `code` | 3 | UniversalBlock | ✅ full | ✅ |
| 11 | `vector_search` | 2 | UniversalBlock | ✅ full | ✅ |
| 12 | `zvec` | 2 | UniversalBlock | ✅ full | ✅ |
| 13 | `cache_manager` | 0 | UniversalBlock | ✅ full | ✅ |
| 14 | `file_hasher` | 0 | UniversalBlock | ✅ full | ✅ |
| 15 | `orchestrator` | 2 | UniversalBlock + TypedBlock | ✅ full | ✅ |
| 16 | `validation` | 3 | UniversalBlock | ✅ full | ✅ |
| 17 | `async_processor` | 0 | UniversalBlock | ✅ full | ✅ |

### What makes them “almost perfect”

#### 1. Dual registration (runtime + store)

- **`app/blocks/__init__.py`:** lazy `BLOCK_REGISTRY` entry `(module, ClassName)`.
- **`block_registry/{id}/`:** `block.json` + `block.py` adapter + `Dockerfile`.

#### 2. `block.json` manifest (copy from `pdf`)

Required keys enforced by audit:

```json
{
  "id": "pdf",
  "name": "Pdf",
  "version": "2.0.0",
  "author": "Cerebrum Team",
  "description": "Extract text from PDF files",
  "layer": 3,
  "requires": [],
  "inputs": [
    {"name": "input", "type": "file", "required": false, "description": "Upload PDF..."},
    {"name": "extract_tables", "type": "boolean", "required": false, "default": true}
  ],
  "outputs": [
    {"name": "text", "type": "text", "description": "Text"},
    {"name": "pages", "type": "number", "description": "Pages"}
  ],
  "execution": {"type": "docker", "image": "ghcr.io/cerebrum-blocks/pdf:latest"},
  "ui_schema": [
    {"name": "input", "widget": "file", "label": "Upload PDF..."},
    {"name": "extract_tables", "widget": "toggle", "label": "Extract Tables"}
  ],
  "tags": ["domain", "documents", "pdf", "typed"]
}
```

Every input has a matching widget; `ui_schema` is an **array**, not an object.

#### 3. Universal adapter (copy from `pdf/block.py`)

```python
def run(**kwargs):
    block_cls = BLOCK_REGISTRY["pdf"]
    instance = block_cls()
    input_data = kwargs.get("input", kwargs)
    params = {k: v for k, v in kwargs.items() if k != "input"}
    envelope = _run_async(instance.execute(input_data, params))
    if envelope.get("status") == "error":
        raise RuntimeError(...)
    return envelope.get("result", envelope)
```

Pattern: **`run()` → `execute()` envelope → `process()`** — never call `process()` directly from adapters.

#### 4. Python block class contract

From `UniversalBlock` / `TypedBlock`:

| Field | Purpose |
|-------|---------|
| `name`, `version`, `description` | Identity |
| `layer` | Init order (0=infra → 5=interface) |
| `tags` | Store discovery / filtering |
| `requires` | Assembler dependency wiring |
| `ui_schema` | Universal UI Shell (dict form in Python) |
| `async def process(...)` | Business logic |
| `execute()` (inherited) | Timing, envelope, error normalization |

TypedBlock adds `input_schema` / `output_schema` with `ContentType` validation (`pdf`, `ocr`, `construction_v2`).

#### 5. Execute / process contract

```python
# universal_base.py — subclasses implement process(); callers/adapters use execute()
async def execute(self, input_data, params=None) -> Dict:
    # Returns {block, request_id, status, result, confidence, metadata, processing_time_ms}
```

#### 6. Domain-agnostic virgin policy

Generic blocks must not auto-inject domain prompts or construction logic. Domain kits and containers supply policy (`DomainContainer.chat()`, kit prompts).

**Known violations even in the 17:** `chat` (`CONSTRUCTION_KEYWORDS` offline fallback), `document_engine` / `image` / `orchestrator` (construction string references in code or manifest tags).

---

## Full block inventory

### Category A — Generic reference (17)

Listed above. Virgin boot default.

### Category B — Extended platform (38)

Legacy full boot when `CEREBRUM_VIRGIN=false`. All have `block_registry/` entries.

`adaptive_router`, `agent_swarm`, `analytics`, `android_drive`, `audit`, `auth`, `billing`, `capture`, `config`, `context_broker`, `dashboard`, `database`, `discovery`, `documentation`, `email`, `error_tracking`, `event_bus`, `failover`, `google_drive`, `health_check`, `knowledge`, `library_container`, `llm_enhancer`, `local_drive`, `migration`, `monitoring`, `notification`, `ocr_v2`, `onedrive`, `payment_split`, `pdf_v2`, `queue`, `rate_limiter`, `review`, `sandbox`, `secrets`, `skills`, `storage`, `team`, `traffic_manager`, `vector`, `version`, `webhook`, `workflow`

### Category C — Construction kit (18)

Ship via `block_store/kits/construction/` + `CEREBRUM_DOMAIN_KITS=construction`.

`bim`, `bim_extractor`, `boq_processor`, `construction_v2`, `drawing_qto`, `formula_executor`, `formula_executor_v2`*, `historical_benchmark`, `jetson_gateway`, `learning_engine`, `llm_enhancer`, `primavera_parser`, `project_reasoner`*, `recommendation_template`, `smart_orchestrator`, `spec_analyzer`, `sympy_reasoning`

\* `formula_executor_v2`, `project_reasoner` — in kit manifest + bundle only; **not** in `app/blocks/` root or `block_registry/` yet.

Helper (not a block): `_procedure_routing.py`.

### Category D — Legacy / duplicate

| Block | Issue |
|-------|-------|
| `pdf_v2`, `ocr_v2` | Parallel implementations; v1 blocks remain canonical for virgin boot |
| `llm_enhancer` | Construction-tagged but registered in extended boot |
| `agent_swarm`, `smart_orchestrator` | Overlap with `orchestrator` / `workflow` — document ownership |

### Category E — Stub / orphan

| Item | Issue |
|------|-------|
| `memory` | Full Python impl + `ui_schema`; **no** `block_registry/`; required by 15+ manifests |
| `container` | Meta-block; no manifest, no `ui_schema`; superseded by `DomainContainer` |
| `container_*.py` (7 files) | Internal container slices — not registry blocks |
| `sandbox/block.py` | Standalone adapter — does **not** use `BLOCK_REGISTRY` + `execute()` |

### Category F — Missing from repo (docs only)

`mcp_adapter`, `mcp_consumer` — referenced in `generic_blocks.md` extended table; no `app/blocks/` implementation in this repo.

---

## Gap analysis matrix

Criteria: **M** manifest, **A** adapter (`run`+`execute`), **D** Dockerfile, **U** ui_schema complete (registry), **P** Python ui_schema, **T** typed I/O, **X** tests, **G** no domain hardcode (virgin/generic only).

### Reference blocks — residual gaps

| Block | M | A | D | U | P | T | X | G | Notes |
|-------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:------|
| pdf | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Gold standard |
| ocr | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | |
| image | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ⚠️ | construction strings |
| document_engine | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ⚠️ | construction tags in manifest |
| chat | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | `CONSTRUCTION_KEYWORDS` |
| translate | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | |
| voice | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | |
| web | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | |
| search | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | |
| code | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | sandbox hardening separate |
| vector_search | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | |
| zvec | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | |
| cache_manager | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | |
| file_hasher | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | |
| orchestrator | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ | requires `memory` (orphan) |
| validation | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | empty description in manifest |
| async_processor | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | |

### Non-reference — structural gaps (score = missing criteria count)

| Block | Category | Gaps |
|-------|----------|------|
| **memory** | orphan | No M/A/D; blocks orchestrator/auth/vector deps |
| **container** | orphan | No M/A/D/P |
| **formula_executor_v2** | kit WIP | No app root, no registry |
| **project_reasoner** | kit WIP | No app root, no registry |
| **sandbox** | extended | Adapter bypasses `execute()` envelope |
| **chat** | reference | Domain hardcode (policy) |
| **document_engine** | reference | No tests; construction manifest tags |
| **skills** | extended | Construction refs; no tests |
| **context_broker** | extended | Construction refs; no tests |
| **traffic_manager** | extended | Construction refs |
| **discovery** | extended | Construction refs; no tests |
| **pdf_v2 / ocr_v2** | duplicate | Consolidation / deprecation path needed |

### Extended platform — test coverage gaps (registry OK, no dedicated tests)

`adaptive_router`, `analytics`, `audit`, `auth`, `billing`, `config`, `dashboard`, `database`, `documentation`, `email`, `error_tracking`, `event_bus`, `failover`, `health_check`, `migration`, `monitoring`, `notification`, `payment_split`, `queue`, `rate_limiter`, `review`, `secrets`, `storage`, `team`, `traffic_manager`, `vector`, `version`, `webhook`

(~27 blocks — manifest-complete but unverified in CI)

---

## Reference standard (implementation template)

Use **`pdf`** as the canonical copy source; use **`orchestrator`** for multi-input/param-heavy blocks; use **`validation`** for action-select + many params.

### Per-block checklist

- [ ] **Identity:** `name` matches folder id and `block.json` `"id"`.
- [ ] **Manifest:** All audit required keys; `ui_schema` array covers every `inputs[].name`.
- [ ] **Adapter:** `block_registry/{id}/block.py` with `run(**kwargs)` calling `instance.execute()`.
- [ ] **Docker:** `Dockerfile` + `execution.image` in manifest.
- [ ] **Python class:** `UniversalBlock` or `TypedBlock`; `layer`, `tags`, `requires`, `description`.
- [ ] **UI:** Python `ui_schema` dict aligned with manifest widgets (codegen or manual sync).
- [ ] **I/O:** Typed schemas where block participates in chains (`TypedBlock`).
- [ ] **Registry boot:** Entry in `_GENERIC_BLOCK_DEFS` or `_EXTENDED_BLOCK_DEFS` / kit loader as appropriate.
- [ ] **Tests:** `tests/blocks/test_{id}.py` with smoke `process()` + adapter `run()` test.
- [ ] **Domain boundary:** Generic/extended platform blocks — no construction prompts, PRC rules, or RSMeans logic.
- [ ] **Docs:** One-line entry in `generic_blocks.md` or kit manifest if domain-specific.
- [ ] **CI:** Passes `audit_block_standards.py` and `test_block_registry.py {id}`.

### Codegen shortcut

```bash
python scripts/generate_block_registry.py   # manifest + adapter + Dockerfile from app/blocks
python scripts/audit_block_standards.py     # verify
python scripts/test_block_registry.py {id}  # smoke test
```

---

## Priority tiers

### Tier 1 — Blockers (1–2 weeks)

Infrastructure and policy fixes that affect virgin boot or kit install.

| Work item | Blocks | Effort |
|-----------|--------|--------|
| Promote `memory` to full registry | `memory` | 0.5 d |
| Fix `orchestrator` dependency chain | `memory`, `traffic_manager` | 0.5 d |
| Strip domain hardcode from virgin `chat` | `chat` | 1 d |
| Promote kit WIP blocks | `formula_executor_v2`, `project_reasoner` | 2 d each |
| Align `sandbox` adapter to universal pattern | `sandbox` | 1 d |
| Add `document_engine` tests + de-domain manifest tags | `document_engine` | 1 d |

**Tier 1 total:** ~8 dev-days

### Tier 2 — Extended platform elevation (2–4 weeks)

Bring legacy-boot blocks to reference quality (tests + domain cleanup + TypedBlock where chained).

| Batch | Blocks | Effort |
|-------|--------|--------|
| **2a — Infra core** | `config`, `database`, `queue`, `secrets`, `migration`, `event_bus` | 3 d |
| **2b — Observability** | `monitoring`, `health_check`, `analytics`, `error_tracking`, `audit` | 4 d |
| **2c — Security / traffic** | `auth`, `rate_limiter`, `failover`, `traffic_manager`, `adaptive_router` | 4 d |
| **2d — Integrations** | `email`, `webhook`, `notification`, drives (`local/google/onedrive/android`), `storage` | 4 d |
| **2e — Platform services** | `billing`, `team`, `payment_split`, `review`, `discovery`, `dashboard`, `documentation`, `version` | 5 d |
| **2f — AI extended** | `knowledge`, `capture`, `workflow`, `agent_swarm`, `vector`, `skills`, `llm_enhancer`, `context_broker`, `library_container` | 6 d |

**Tier 2 total:** ~26 dev-days (parallelizable)

### Tier 3 — Construction kit polish (2–3 weeks)

Domain blocks are manifest-complete; elevation = tests, dedup, container routing.

| Batch | Blocks | Effort |
|-------|--------|--------|
| **3a — Core AEC** | `construction_v2`, `boq_processor`, `spec_analyzer`, `drawing_qto` | 4 d |
| **3b — Schedule / BIM** | `primavera_parser`, `bim`, `bim_extractor`, `jetson_gateway` | 4 d |
| **3c — Reasoning / formulas** | `formula_executor`, `formula_executor_v2`, `sympy_reasoning`, `project_reasoner`, `smart_orchestrator` | 5 d |
| **3d — Learning / analytics** | `learning_engine`, `historical_benchmark`, `recommendation_template` | 3 d |
| **3e — Dedup** | Deprecate or merge `pdf_v2`/`ocr_v2`; resolve `container` vs `DomainContainer` | 2 d |

**Tier 3 total:** ~18 dev-days

### Grand total estimate

| Tier | Effort | Calendar (3 agents parallel) |
|------|--------|------------------------------|
| Tier 1 | 8 d | ~3 d |
| Tier 2 | 26 d | ~9 d |
| Tier 3 | 18 d | ~6 d |
| **Combined** | **~52 dev-days** | **~18 d** |

Add 20% buffer for CI/Docker image rebuilds → **~62 dev-days / ~22 calendar days**.

---

## Parallel workstream assignments

| Agent / stream | Owns | Tier | Deliverables |
|----------------|------|------|--------------|
| **WS-A — Registry & infra** | `memory`, `sandbox`, adapter codegen | 1 | Registry entries, orchestrator deps green |
| **WS-B — Virgin purity** | `chat`, `document_engine`, generic domain audit | 1 | No construction leakage in virgin 17 |
| **WS-C — Kit promotion** | `formula_executor_v2`, `project_reasoner`, publish script | 1 + 3 | Blocks in `app/blocks/`, registry, kit bundle sync |
| **WS-D — Platform infra tests** | Tier 2a + 2b blocks | 2 | Test files + CI job per block |
| **WS-E — Platform security & integrations** | Tier 2c + 2d | 2 | Tests + TypedBlock for chained blocks |
| **WS-F — Store & enterprise** | Tier 2e | 2 | billing/team/payment_split elevation |
| **WS-G — AI pipeline** | Tier 2f | 2 | workflow/agent_swarm/knowledge parity |
| **WS-H — Construction core** | Tier 3a–3d | 3 | Kit block tests + container wiring |
| **WS-I — Dedup & docs** | v2 blocks, `container`, doc renames | 3 | ADR for pdf/ocr v2; fix `validation_pipeline` naming |

### Suggested sprint order

1. **Sprint 1:** WS-A + WS-B + WS-C (Tier 1)
2. **Sprint 2:** WS-D + WS-E (Tier 2a–2c)
3. **Sprint 3:** WS-F + WS-G (Tier 2d–2f)
4. **Sprint 4:** WS-H + WS-I (Tier 3)

---

## Top 10 blocks needing work (priority order)

| Rank | Block | Why |
|------|-------|-----|
| 1 | **`memory`** | No registry; hard dependency of orchestrator, auth, vector, queue, etc. |
| 2 | **`chat`** | Virgin generic block with construction keyword fallback — charter violation |
| 3 | **`formula_executor_v2`** | In kit manifest; missing from platform tree and registry |
| 4 | **`project_reasoner`** | Same as above — kit install gap |
| 5 | **`sandbox`** | Non-standard adapter; security-sensitive; validation block depends on it |
| 6 | **`document_engine`** | Virgin block with no tests; construction-tagged manifest |
| 7 | **`orchestrator`** | Reference block blocked by missing `memory` registry wiring |
| 8 | **`skills`** | Tagged `ai/core` but construction-coupled; no tests |
| 9 | **`traffic_manager`** | Infra block with construction strings; no tests |
| 10 | **`container`** | Orphan meta-block — clarify vs `DomainContainer` or add registry |

---

## Verification gates

Before marking any block “elevated”:

1. `python scripts/audit_block_standards.py` — 0 errors for that block's folder
2. `python scripts/test_block_registry.py {block_id}` — pass
3. `pytest tests/blocks/test_{block_id}.py -q` — pass (new or existing)
4. For virgin-eligible blocks: grep confirms no domain keywords in default code paths
5. Docker image builds: `docker build -t test/{block_id} block_registry/{block_id}/`

---

## Related docs

- [generic_blocks.md](./generic_blocks.md) — Virgin 17 list
- [platform_charter.md](./platform_charter.md) — Fork vs store model
- [block_registry/README.md](../block_registry/README.md) — Registry structure
- `scripts/audit_block_standards.py` — Manifest linter

---

*Plan authored 2026-06-10. Implementation tracked by tier/workstream above.*
