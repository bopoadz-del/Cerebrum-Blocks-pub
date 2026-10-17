# Container Migration Manifest

**Authoritative source:** [bopoadz-del/The_Fork](https://github.com/bopoadz-del/The_Fork) (`main`)  
**Store layer:** Cerebrum-Blocks — discovery, publish, install  
**Status:** Strategy locked — **Fork live, CB is the store**

---

## Agreed architecture (2026-06-10)

| Product | Role | What changes |
|---------|------|--------------|
| **The Fork** | Live production runtime | Battle-tested monolith, real data, Masterise pitch, fine-tuned adapter incoming. **Do not migrate into CB.** |
| **Cerebrum-Blocks** | Block Store — discovery + install | Publish Fork-authored kits; consumers install without forking the whole repo |

### Decisions

| Topic | Decision |
|-------|----------|
| Fork chat policy | **Keep Fork `chat.py` v3.0** (RAG, local LLM, TypedBlock, prompt file security). **Remove only** the 6-line auto-inject of `construction_expert.txt` — done locally on `The_Fork/app/blocks/chat.py`. Do **not** replace Fork chat with CB's simpler block. |
| `construction_types` | **Stays in Fork** (`app/core/construction_types.py`). Published to CB store as part of the construction kit bundle. |
| Monolith split | **Defer.** Fork 7k-line container stays intact until a failing test forces a split. |
| Block Store install API | **Build now** — it's the point of CB. Implemented at `/store/containers` + `/v1/store/containers`. |

### Publish → discover → install flow

```
The Fork (main)  ──publish──►  block_store/kits/construction/bundle/
                                      │
                                      ▼
                         GET /store/containers  (discovery, public)
                                      │
                                      ▼
                         POST /store/containers/construction/install  (auth)
                                      │
                                      ▼
                         Consumer instance app/ tree
```

**Scripts & paths:**

- Kit manifest: `block_store/kits/construction/manifest.json`
- Publish from Fork: `python scripts/publish_construction_kit.py`
- Store service: `app/core/container_kit_store.py`
- API router: `app/routers/store.py`

### Chat block policy (agreed)

**Fork chat is the production implementation.** CB chat is a thinner dev stub (~310 lines vs Fork ~575 lines) and is not a merge target.

| Capability | Fork `chat.py` v3.0 | CB `chat.py` v2.0 |
|------------|---------------------|-------------------|
| TypedBlock + schemas | Yes | No (`UniversalBlock`) |
| RAG (`use_rag` + `project_id`) | Yes | No |
| Local fine-tuned model | Yes | No |
| Ollama / llama.cpp fallback | Yes | No |
| Secure `system_prompt_file` loading | Yes | No |
| Default domain prompt | ~~`construction_expert.txt`~~ **removed** | None (but offline fallback still construction-keyed) |

**Layering (correct):**

1. **`ChatBlock`** — mechanics only: providers, RAG, local model, prompt resolution when the **caller** passes `system_prompt` / `system_prompt_file`.
2. **`ConstructionContainer.chat()`** — domain policy: defaults to `construction_evm.md`, `use_rag=True`.
3. **`construction_knowledge` / expert prompt** — PRC rules for blocks that need them (`construction_v2`), not generic chat defaults.

**What changed on Fork:** deleted the block that forced `construction_expert.txt` on every chat with no caller prompt. Everything else stays Fork-side.

---

## Executive summary

The Fork is the production-hardened reference for domain containers. Its construction kit is a **7,330-line monolith** (`app/containers/construction.py`) that delegates to **15 required blocks** via `BLOCK_REGISTRY`, routes **47 public actions**, and keeps domain knowledge **outside** the container file in separate modules and prompts.

Cerebrum-Blocks has a **larger** local copy of `construction.py` (8,020 lines), but is **missing** the knowledge layer (`construction_knowledge.py`, `construction_types.py`, procedure DB, expert prompts). CB does not publish runtime code — it publishes Fork-authored kits via `block_store/kits/`.

**Key architectural finding:** `ConstructionContainer` does **not** import `construction_knowledge`. Domain rules enter through these paths:

| Path | Mechanism | Domain coupling |
|------|-----------|-----------------|
| Container `chat()` | Injects `system_prompt_file = "construction_evm.md"` | Container-owned policy ✓ |
| `ChatBlock` default | ~~Auto-injects `construction_expert.txt`~~ | **Removed on Fork** — caller/container owns prompt ✓ |
| `construction_v2` block | Imports `ConstructionKnowledge` for PRC validation | Block-owned ✓ |

RAG is domain-agnostic; construction context is prompt + tool layer, not retriever layer.

---

## Fork vs Cerebrum-Blocks (snapshot)

| Artifact | The Fork (GitHub) | Cerebrum-Blocks |
|----------|-------------------|-----------------|
| `app/containers/construction.py` | 7,330 lines / 363 KB | 8,020 lines / 412 KB (local drift) |
| `app/core/construction_knowledge.py` | 508 lines | **Missing** |
| `app/core/construction_types.py` | Present (3 dataclasses) | **Missing** |
| `app/core/construction_constants.py` | Present | **Missing** |
| `app/prompts/construction_expert.txt` | Present | **Missing** |
| `app/prompts/construction_evm.md` | Present | **Missing** |
| `app/data/procedures/procedures_db.json` | Present | **Missing** |
| `app/knowledge/construction_kb.json` | Present | **Missing** |
| `app/blocks/chat.py` | v3.0 TypedBlock, RAG, local LLM; prompt hardcode **removed** | v2.0 stub; no prompt file default (offline fallback still construction-keyed) |
| `app/blocks/construction_v2.py` | Uses `ConstructionKnowledge` | Present (will break without knowledge module) |
| Physical `containers/construction/` folder | **No** (same monolith pattern) | **No** |

**Recommendation:** Do **not** merge Fork into CB wholesale. Publish kits from Fork; CB installs on demand. Fork chat stays authoritative — only the prompt auto-inject was removed.

---

## 1. `app/containers/construction.py` — full map

### 1.1 Class metadata

```python
class ConstructionContainer(UniversalContainer):
    name = "construction"
    version = "3.1"
    layer = 3
    tags = ["domain", "container", "aec", "construction", "bim"]
```

### 1.2 Top-level imports (only 2 app modules)

| Import | Role |
|--------|------|
| `app.core.universal_base.UniversalContainer` | Base class; `process()` delegates to `route(action)` |
| `app.core.construction_types.{Measurement, SpecItem, RiskItem}` | Shared dataclasses (also used by `construction_v2`) |

All other dependencies are **lazy-imported inside methods** (`from app.blocks import BLOCK_REGISTRY`).

### 1.3 Required blocks (`requires = [...]`)

**Infrastructure (generic — candidate `app/blocks/core/`):**

- `pdf`, `ocr`, `image`

**Construction intelligence (candidate `app/blocks/construction/`):**

- `boq_processor`, `spec_analyzer`, `sympy_reasoning`
- `drawing_qto`, `primavera_parser`, `smart_orchestrator`
- `jetson_gateway`, `formula_executor`, `bim_extractor`
- `learning_engine`, `recommendation_template`

### 1.4 Block delegation (`_resolve_block` / `_get_*_block`)

| Block name | Resolve count | Notes |
|------------|---------------|-------|
| `bim_extractor` | 6 | BIM / IFC workflows |
| `primavera_parser` | 4 | Schedule / XER / CPM |
| `spec_analyzer` | 4 | CSI division parsing |
| `historical_benchmark` | 4 | Legacy; comment says replaced by `learning_engine` |
| `boq_processor` | 2 | BOQ extraction |
| `chat` | 1 | Conversational entry |
| `document_engine`, `sympy_reasoning`, `drawing_qto`, `smart_orchestrator`, `jetson_gateway`, `formula_executor`, `learning_engine`, `recommendation_template` | 1 each | Thin delegate wrappers |

Also uses `file_hasher`, `cache_manager`, `llm_enhancer` via direct `BLOCK_REGISTRY` access (not in `requires`).

### 1.5 String reference scan (inside container file)

| Symbol | Count | Meaning |
|--------|-------|---------|
| `construction_knowledge` | 0 | Knowledge **not** wired into container |
| `construction_expert` | 0 | Expert prompt not referenced here |
| `construction_evm` | 1 | Used in `chat()` default prompt |
| `construction_constants` | 4 | Inline domain defaults imported at use sites |
| `BLOCK_REGISTRY` | 12 | Runtime block lookup |
| `_resolve_block` | 20 | Delegation hub |
| `use_rag` | 5 | Chat defaults RAG **on** |
| `system_prompt_file` | 4 | Prompt injection sites |

### 1.6 Method inventory

- **262 methods** total on `ConstructionContainer`
- **~176 private helpers** (`_*`)
- **~47 action handlers** exposed via `route()` / `get_actions()`

### 1.7 Action router

`UniversalContainer.process()` (inherited) reads `params["action"]` and calls `route()`.  
`route()` and `get_actions()` mirror the same handler map (47 entries):

| Category | Actions |
|----------|---------|
| **Chat & documents** | `chat`, `process_document`, `auto_pipeline`, `intelligent_workflow`, `health_check` |
| **QA / site** | `qa_qc_inspection`, `safety_compliance_audit`, `daily_site_report`, `progress_tracker`, `as_built_deviation_report` |
| **Quantities & cost** | `extract_quantities`, `estimate_costs`, `generate_cost_estimate`, `payment_certificate`, `change_order_impact`, `value_engineering` |
| **Specs & contracts** | `process_specification_full`, `process_contract`, `submittal_log_generator`, `rfi_generator` |
| **Schedule** | `parse_primavera_schedule`, `forensic_delay_analysis`, `resource_histogram`, `generate_wbs` |
| **BIM** | `bim_analysis`, `bim_clash_detection`, `digital_twin_sync` |
| **Procurement & tender** | `procurement_list_generator`, `procurement_analysis`, `procurement_optimizer`, `tender_bid_analysis`, `variation_order_manager` |
| **Risk & claims** | `risk_register_auto_populate`, `claims_builder` |
| **Sustainability** | `carbon_footprint_calculator`, `generate_carbon_report`, `esg_sustainability_report` |
| **Lifecycle** | `warranty_maintenance_schedule`, `commissioning_checklist`, `om_manual_generator`, `cash_flow_forecast` |
| **Block delegates (Week 1–4)** | `boq_process`, `spec_analyze`, `sympy_reason`, `drawing_qto`, `primavera_parse`, `orchestrate`, `jetson_dispatch`, `formula_execute`, `bim_extract`, `learn`, `benchmark_lookup`, `recommend` |

### 1.8 `chat()` behavior (domain injection point)

```python
async def chat(self, input_data, params=None):
    chat_block = self._resolve_block("chat")
    merged = dict(params or {})
    if "use_rag" not in merged: merged["use_rag"] = True
    if not caller_supplied_prompt:
        merged["system_prompt_file"] = "construction_evm.md"
    return await chat_block.process(input_data, merged)
```

**Migration target:** `merged["system_prompt_file"] = self.system_prompt_file` where the container declares its prompt path, not a hardcoded filename.

### 1.9 Supporting Fork files (move with kit)

| Path | Purpose | Migration |
|------|---------|-----------|
| `app/prompts/construction_evm.md` | Container chat default | → `containers/construction/prompts/evm.md` |
| `app/prompts/construction_expert.txt` | Expert system prompt | → `containers/construction/prompts/expert.txt` |
| `app/data/procedures/procedures_db.json` | PRC procedure definitions | → `containers/construction/data/procedures_db.json` |
| `app/knowledge/construction_kb.json` | Static KB snippets | → `containers/construction/knowledge/kb.json` |
| `app/core/construction_types.py` | Shared dataclasses | → `containers/construction/types.py` or keep in core if cross-block |
| `app/core/construction_constants.py` | Grade tables, defaults | → `containers/construction/constants.py` |

---

## 2. `app/core/construction_knowledge.py` — classification

508 lines. Loads `procedures_db.json` and `construction_expert.txt`. Consumed by **`construction_v2`** and tests — **not** by the container monolith.

### 2.1 Copy verbatim → `containers/construction/knowledge.py`

| Symbol | Type | Why construction-specific |
|--------|------|---------------------------|
| `_DB_PATH`, `_SYSTEM_PROMPT_PATH` | paths | Point to kit data |
| `_load_db()`, `get_procedure()` | functions | PRC procedure lookup |
| `get_system_prompt()` | function | Returns expert prompt text |
| `CRITICAL_RULES` | dict | PRC-402/501/502/605/606 business rules |
| `enforce_critical_rules()` | function | Scans text for rule violations |
| `generate_doc_number()` | function | RFI/NCR/VO/DD numbering schemes |
| `VALID_DESIGN_STATUSES`, `FORBIDDEN_DESIGN_STATUSES` | constants | PRC-501 design review |
| `validate_design_status()` | function | Design status gate |
| `check_review_timeline()` | function | 7-day distribution rule (PRC-501) |
| `VALID_NCR_DISPOSITIONS`, `NCR_WORKFLOW_SEQUENCE` | constants | PRC-402 NCR workflow |
| `validate_ncr_disposition()`, `next_ncr_status()` | functions | NCR state machine |
| `ConstructionKnowledge` | class | Facade over above |

### 2.2 Copy + rename → shared `app/core/domain_math.py` (or base kit mixin)

These are **methodology-shaped** but currently encode construction procedure IDs in docstrings. Extract numeric logic, parameterize labels:

| Function | Generic core | Construction wrapper |
|----------|--------------|----------------------|
| `score_risk(probability, impact)` | 1–5 matrix → GREEN/AMBER/RED | Keep PRC-302 reference in construction kit docs |
| `calculate_payment(...)` | Retention, cumulative certified, cap | PRC-605 defaults |
| `calculate_evm(...)` | PV/EV/AC, CPI/SPI, EAC | EVM for projects (rename params) |
| `evaluate_tender(...)` | Weighted criteria scoring | PRC-603 tender eval rules |

### 2.3 Needs abstraction before multi-domain reuse

| Concern | Current state | Target |
|---------|---------------|--------|
| Path resolution | `Path(__file__).parent.parent / "data" / ...` | `DomainContainer.data_dir` property |
| Class name | `ConstructionKnowledge` | `ConstructionKnowledge(DomainKnowledge)` or kit-local name |
| Chat default in `ChatBlock` | ~~Fork hardcoded `construction_expert.txt`~~ | **Removed** — container or caller supplies prompt |
| `construction_v2` import path | `app.core.construction_knowledge` | `containers.construction.knowledge` or injected at install |

---

## 3. Related coupling outside the container

| File | Coupling | Action |
|------|----------|--------|
| `app/blocks/chat.py` (Fork) | ~~Default `construction_expert.txt`~~ | **Done** — keep Fork v3 chat; no CB replacement |
| `app/blocks/construction_v2.py` | `ConstructionKnowledge`, `construction_types` | Move imports to kit paths after extraction |
| `app/blocks/_procedure_routing.py` | Procedure IDs | Audit during kit install (if present in CB) |
| `scripts/generate_knowledge_scenarios.py` | Test data gen | Update paths post-move |
| `tests/test_knowledge_scenarios.py` | Knowledge unit tests | Co-locate with kit |

---

## 4. Migration manifest — file actions

### 4.1 Phase A — Publish from Fork to store bundle

Kit artifacts land under `block_store/kits/construction/bundle/` with **Fork paths preserved** (not relocated to `containers/construction/`):

| Source (Fork) | Bundle dest (same relative path) |
|---------------|----------------------------------|
| `app/containers/construction.py` | `bundle/app/containers/construction.py` |
| `app/core/construction_knowledge.py` | `bundle/app/core/construction_knowledge.py` |
| `app/core/construction_types.py` | `bundle/app/core/construction_types.py` |
| `app/core/construction_constants.py` | `bundle/app/core/construction_constants.py` |
| `app/blocks/construction_v2.py` | `bundle/app/blocks/construction_v2.py` |
| `app/prompts/construction_expert.txt` | `bundle/app/prompts/construction_expert.txt` |
| `app/prompts/construction_evm.md` | `bundle/app/prompts/construction_evm.md` |
| `app/data/procedures/procedures_db.json` | `bundle/app/data/procedures/procedures_db.json` |
| `app/knowledge/construction_kb.json` | `bundle/app/knowledge/construction_kb.json` |

Run: `python scripts/publish_construction_kit.py`

Full kit scope (32 artifacts): container monolith, `construction_v2` + 14 domain blocks (`boq_processor` … `project_reasoner`), support modules (`plan_executor`, `sandbox`, `pm_computations`, schemas), prompts, and knowledge data. Generic platform blocks (`pdf`, `ocr`, `image`) are declared in the manifest but not bundled.

### 4.2 Phase B — Blocks by folder

**`app/blocks/core/` (generic, unchanged interface):**

| Block | Role |
|-------|------|
| `pdf` | Document ingestion |
| `ocr` | Text extraction |
| `image` | Photo / drawing raster |
| `chat` | LLM mechanics (no domain default prompt) |
| `file_hasher` | Cache keys (used by container) |
| `cache_manager` | Result caching |
| `document_engine` | Generic doc pipeline |

**`app/blocks/construction/` (domain blocks from Fork `requires`):**

| Block | Container delegate method |
|-------|---------------------------|
| `boq_processor` | `boq_process` |
| `spec_analyzer` | `spec_analyze` |
| `sympy_reasoning` | `sympy_reason` |
| `drawing_qto` | `drawing_qto` |
| `primavera_parser` | `primavera_parse` |
| `smart_orchestrator` | `orchestrate` |
| `jetson_gateway` | `jetson_dispatch` |
| `formula_executor` | `formula_execute` |
| `bim_extractor` | `bim_extract` |
| `learning_engine` | `learn` |
| `recommendation_template` | `recommend` |

Optional legacy: `historical_benchmark` → `benchmark_lookup` (deprecate after `learning_engine` parity).

### 4.3 Phase C — New abstractions

**`containers/base.py` — minimum `DomainContainer` interface (~50 lines):**

```python
class DomainContainer(UniversalContainer):
    """Kit entry point: prompt + knowledge + block list + action map."""

    name: str
    description: str
    version: str = "1.0.0"
    system_prompt_file: str = ""          # relative to kit prompts/
    knowledge_class: type | None = None   # e.g. ConstructionKnowledge
    kit_root: Path | None = None          # set at install time

    def resolve_prompt(self, filename: str | None = None) -> str:
        """Load prompt text from kit_root/prompts/."""

    def get_rag_filters(self) -> dict | None:
        """Optional metadata filters for retriever; default None."""

    async def chat(self, input_data, params=None) -> dict:
        """Inject self.system_prompt_file unless caller overrides."""

    @abstractmethod
    def get_actions(self) -> dict[str, Callable]:
        ...

    async def route(self, action, input_data, params) -> dict:
        handler = self.get_actions().get(action)
        ...
```

**Shim during transition:**

```python
# app/containers/construction.py
from containers.construction.container import ConstructionContainer  # re-export
```

### 4.4 Phase D — Strip for empty kit template

When cloning for law/medical/finance, **omit**:

- All files under `containers/construction/`
- Construction blocks under `app/blocks/construction/`
- Fork `chat.py` construction default (already absent in CB)
- `construction_v2` unless domain kit installed

**Keep in template:**

- `containers/base.py`
- `app/blocks/core/*`
- `UniversalContainer` / `UniversalBlock` in `app/core/universal_base.py`
- Block registry generator
- RAG retriever (domain-agnostic)

### 4.5 Phase E — Block Store API (future)

| Endpoint | Behavior |
|----------|----------|
| `GET /api/store/containers` | List installable kits (manifest JSON per kit) |
| `POST /api/store/containers/{id}/install` | Copy blocks → `app/blocks/{domain}/`, register container, load prompts |

Each kit ships a **`manifest.json`**:

```json
{
  "id": "construction",
  "version": "3.1",
  "blocks": ["boq_processor", "spec_analyzer", "..."],
  "container_class": "containers.construction.container.ConstructionContainer",
  "prompts": ["expert.txt", "evm.md"],
  "data": ["procedures_db.json"]
}
```

---

## 5. Risk register (migration)

| Risk | Severity | Mitigation |
|------|----------|------------|
| CB `construction.py` drift vs Fork | High | Diff and cherry-pick `_safe_float` / audit fixes into extracted module |
| Missing knowledge breaks `construction_v2` | High | Phase A before enabling v2 block |
| Dual prompt defaults (container EVM vs chat expert) | ~~Medium~~ Closed | Fork chat hardcode removed; container owns `construction_evm.md` |
| 7k-line monolith hard to maintain | Medium | Phase 2 split: `document.py`, `schedule.py`, `procurement.py` mixins |
| `historical_benchmark` vs `learning_engine` | Low | Keep delegate; document deprecation |
| Registry paths after folder move | Medium | Re-run `generate_block_registry.py --all` |

---

## 6. Implementation order

**Done:**

1. Store API — `GET/POST /store/containers` + `container_kit_store.py`
2. Construction kit manifest + `publish_construction_kit.py` (32/32 bundle artifacts — full domain block suite)
3. Fork chat — removed `construction_expert.txt` auto-inject (local; push to GitHub pending)

**Next:**

4. Push Fork chat fix to GitHub  
5. Store UI — browse kits, install button  
6. CI publish — Fork tag → refresh CB kit bundle  
7. ~~Monolith split~~ — defer until failing test  
8. Optional: cherry-pick `_safe_float` from CB `construction.py` **into Fork** if audit fixes are still needed there

---

## 7. Audit tooling

Regenerate stats from local Fork clone (should match GitHub `main`):

```bash
python scripts/audit_fork_container.py
```

GitHub file SHA (2026-06-10): `876a6446fba0072eaf8bb087c10e6f54d2692765` — `app/containers/construction.py`, 363,558 bytes.

---

## 8. Resolved decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Source of truth | **Fork `main` only** for runtime code |
| 2 | `construction_types` | **Stays in Fork** at `app/core/construction_types.py`; published in kit bundle as-is |
| 3 | Monolith split | **Defer** until a failing test forces it |
| 4 | CB role | **Store layer** — publish / discover / install, not full Fork migration |
| 5 | Fork chat | **Keep Fork v3 chat**; remove prompt auto-inject only — **not** CB chat swap |
| 6 | Kit install model | **Copy-on-install** from `block_store/kits/{id}/bundle/` → consumer `app/` tree |
| 7 | `container` meta-block | **Orphan** — `app/blocks/container.py` has no `block_registry/` entry. Superseded by `app/containers/` (`DomainContainer` / kit containers). Kept for legacy `ContainerBlock` API; not elevated to registry. |

---

*Fork = runtime. Cerebrum-Blocks = store. Store API + construction kit bundle implemented; Fork chat prompt hardcode removed locally — push to GitHub pending.*
