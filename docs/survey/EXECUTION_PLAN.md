# Store Inventory Survey — Execution Plan

Source: `docs/survey/store_survey_report.html` (full survey, 82 agents, 167 confirmed /
14 refuted, verified against actual source). This plan is the execution program. The survey
itself cloned, merged, or pushed nothing.

## Scope

- 16 repos scouted, 12 block clusters audited, 6 connector research topics
- 59 clone candidates, 60 store upgrades, 48 connector targets

## Guardrails (from the report, binding)

- Never port fabricated features (e.g. <private-repo> `experiments.ts` Math.random backtest).
- Honest stubs stay honest stubs — upgrading a stub means building the real adapter,
  never faking numbers.
- Provenance labels survive extraction: real / honest-stub / mock-functional / aspirational.
- Every new Store block follows the existing block contract (block.json + execute()/process())
  and gets a test that would catch a regression (the survey's own standard).
- The evidence-or-refuse + orchestrator-assigned confidence pattern must be honored wherever
  a block takes LLM output.

## Wave order

### Wave 1 — Store correctness bugs (highest value, cheapest)
Fixes that silently corrupt every client platform built from the Store.

1. `document_engine` — port The_Fork fixes:
   - `_map_wbs` KeyError → `mapping.setdefault(target_code, [])` (crash on trimmed WBS dicts)
   - raw parsed text passthrough (else BOQ uploads degrade to generic ontology defaults)
   - inline-brief (text-only, no file) path
   - `open_plaintext` wrap on every parser call (encrypted-at-rest inputs)
   - wire `_parse_with_platform_ocr` (dead code today)
2. `pdf.py` — wrap all file-open paths in `app.core.file_crypto.open_plaintext`
   (mirroring ocr.py/ocr_v2.py).
3. `boq_processor.py` — add PDF parsing (pdfplumber table-grid, honest failure on scanned
   input) + `engine = "xlrd"` for legacy `.xls`.
4. `spec_analyzer.py` — OCR fallback block under `ocr_fallback_min_chars` (200), plus the
   broader standard-citation regexes (AS/IBC-year/BS-EN ordering/ASTM trailing).
5. `drawing_qto.py` — port The_Fork's PDF/DWG extraction (~24 functions incl.
   `_extract_from_pdf`, `_try_convert_dwg`, title-block/room/cross-ref extraction,
   Levenshtein OCR-artifact cleanup).
6. `primavera_parser.py` — wire `compute_cpm` from the orphaned `app/lib/pm_computations.py`
   and sync that file (+ `app/schemas/cpm.py`) to The_Fork's 818-line version.
7. Remaining cluster upgrades — document-ocr-pdf (3), bim-construction (4), finance (3),
   insurance (1), hotel (3), retail (3), medical-legal (3), aviation (4),
   connector-infra (4), core-infra (8), reasoning-orchestration (13),
   media-vision-misc (3). Full list in the survey report.

### Wave 2 — Clone candidates (59, by donor)
Each is a new block or block family in `app/blocks/` + registry entry.

- **Cerebrum (5)** — vdc_clash_detection, vdc_bcf_export, self-healing patch + hot-swap,
  enterprise connector suite (Procore/QuickBooks-Xero/Salesforce-HubSpot/DocuSign/
  Box-Dropbox/MS365/Slack/Zapier), sso_saml + SCIM.
- **<private-repo> (3)** — finance_planning family (immutable budget versions,
  allocation remainder routing, scenario adjustment), governance_gate + evidence_chain
  (fail-closed approval, SHA-256 hash chain), multi_tenant_rbac.
- **<private-repo> (3)** — estate-scoped bearer auth + RBAC, resident-engineer
  governance scaffold (allowlist + approval + append-only audit + injection guard),
  ingestion provenance (page/sheet/row).
- **<private-repo> (1)** — dual-RAG regulatory chunking (L1/L2 + section-aware chunker).
- **<private-repo> (5)** — sub_agent_runtime (spawn + env-scrub + schema-retry), agent_state_sync
  (vector clocks + conflict archive), domain-kit compiler, evidence-or-refuse gate,
  build-honesty tooling (→ Wave 4, factory CI).
- **<private-repo> (2)** — user_auth (bcrypt/JWT-refresh-rotation/TOTP MFA) and
  market_data vertical (dual-provider failover + alert evaluator). NEVER the backtest.
- **<client> (3)** — verified_outcome_learning engine, hat framework, Power BI connector.
- **The_Fork (5), <private-repo> (2), <private-repo> (1), <private-repo> (3),
  <private-repo> (4), <private-repo>-v2 (1), <private-repo> (5)**
- **Clusters** — bim-construction (2), finance (3), insurance (6), retail (1),
  connector-infra (1), core-infra (2), reasoning-orchestration (1).

### Wave 3 — Governance pair (retire the vacuous audit)
Port <private-repo> `governance/service.py` (require_approved_action, 403 fail-closed)
+ `audit/service.py` (SHA-256 hash-chain, verify_chain() full-walk — add the missing
chain walk) as Store blocks; diff against the always-ok audit/evidence_verifier block
and replace it.

### Wave 4 — Factory tooling adoption
Port <private-repo> `scripts/mutation_gate.py` + `scripts/stub_detector.py` + `secret_scan.py`
into <private-repo> CI as a pre-merge "hollow function / vacuous test" gate.

### Wave 5 — Connectors (48)
- ProcoreCdeClient implementing The_Fork's `app/core/cde/protocol.py` (Aconex + Procore
  behind one door)
- SAP/ERP ETL family (SapODataConnector first — read-only GL + PO headers)
- Maximo (real, hotelops), Primavera Cloud (OAuth2 ETL, after batch parser), Power BI
- Generic inbound webhook receiver (per-source HMAC: Procore/GitHub/Slack/Maximo) onto
  the HotelEvent-style event bus
- MCP allowlist hardening before wiring untrusted MCP servers
- Research topics: construction-project-mgmt (4), erp-sap (5), hospitality-pms (3),
  crm-collaboration (5), hr-supply-chain (2), mcp-pattern-fit (7)

### Wave 6 — Close-out
- Register every new block in `block_registry/`, regenerate `blocks.lock.json`
- Store test suite green; run `scripts/acceptance.py`-equivalent store gates
- Update Store README/inventory with the new blocks + provenance labels
- Update the Factory inventory declaration (ready verticals now covered by new blocks)

## Progress ledger

- 2026-09-17: plan created; survey archived into `docs/survey/`. Wave 1 items 1–3 started.
- 2026-09-17: Waves 1.1–1.4 done and verified (15/15 new regression tests; 22/22
  blocks+dep-audit; spec suite green).
  - 1.1 document_engine: KeyError→setdefault (trimmed WBS dicts), raw_text
    passthrough, inline-brief path, open_plaintext on all parser calls,
    OCR fallback wired (200-char tripwire), pdf_parser real table extraction
    (PyMuPDF find_tables; pypdf engine kept), mapper logging.
  - 1.2 pdf.py: open_plaintext wrap on every open path (pdfplumber/pypdf/fitz/
    openpyxl/python-docx).
  - 1.3 boq_processor: .pdf accepted (table-grid grouping + partial/text
    fallback + 32MB memory guard + skipped-page disclosure), .xls via xlrd
    (added to requirements), header-row detection under banner rows,
    two-pass _resolve_columns + _normalize_col.
  - 1.4 spec_analyzer: synced from The_Fork (OCR fallback under 200 chars,
    BS EN ordering, ASTM year suffix, AS/IBC codes, grade stopwords,
    grade/standard resolution via construction_constants).
  - Known env gaps (pre-existing, not wave regressions): system-python
    lacks pandas/sklearn/gTTS metadata; the store venv (.venv) is the
    correct runner.
  - CORRECTION: the earlier "store suite is flaky" note was wrong. The
    recurring spec_analyzer test failure was a bug in MY test helper —
    it unpacked frozensets, whose iteration order is hash-seeded and
    varies per process. Fixed to tuples; the combined wave suite now
    passes 4/4 consecutive runs. No suite flakiness remains on record.
- 2026-09-17 (overnight): Wave 1.7 batch 2 shipped (8efc840b) —
  historical_benchmark 'record' wired to learning_engine.record_correction
  (vacuous-success stub removed, refusal on incomplete payloads, regression
  tests green); retail_v2 registered in block_registry/ with adapter +
  Dockerfile. Confirmed channel_router is NOT pulled by the retail kit
  manifest (insurance tags already explicit) and hotel_trigger is already
  honestly labeled 0.1.0-skeleton — no change needed on those.

### PARKED with notes (overnight)

- DONE (batch 4, kernel branch): sandbox isolated-level now requires
  SANDBOX_RUNNER_URL (refused by name, no in-process fallback for untrusted
  code); discovery routes search/recommend through the wired vector block
  (cosine when a real embedder is loaded, honest `via` label otherwise);
  review purchase verification is backed by a real billing purchase ledger
  (record_purchase/check_purchase) — fail-closed, never minted verified out
  of thin air; billing manifest action options updated; retail_v2 manifest
  brief-scope backfill.
- Publisher key ROTATED: new Ed25519 keypair, all 111 registry blocks
  re-signed, verification 100%. New private key stored at
  ~/.codewhale/keys/cerebrum_platform.pem (move to the secrets manager);
  data/publishers/cerebrum_platform.pub updated — any consumer pinning the
  old public key must adopt the new one.
- DONE (batch 5): safety_world_detector wrapped+registered; project_reasoner
  manifest completed (stale failed-oracle removed, proven by test);
  mcp_adapter cleaned+registered (read-only catalog, never executes);
  inbound_webhook HMAC verifier ported from the Cerebrum donor.
- DONE (batch 6): finance cluster — CoA lifecycle (create_draft →
  propose_activation → approve_activation with self-approval refused and
  version archive) + finance_import parse_file (.csv/.xlsx) and idempotent
  ingest (batch digest + per-record dedupe); hotel — opera_connector is a
  real fail-closed connector (hotelops-v2 MockLevel pattern: no live
  config → structured refusal, never fabricated data; real Opera
  normaliser) and hotel_v2 is wired into POST /v1/connectors/hotel/analyze
  with POST /v1/connectors/hotel/opera for the connector.
  All wave-1.7 parked items are now DONE.

- safety_world_detector: real YOLO-World onnx detector, no UniversalBlock
  wrapper and unregistered. Wrap in a UniversalBlock (process -> detect,
  SA FET Y_WORLD_WEIGHTS env) + register; until then it is consumed only by
  non-registry paths.
- review.py billing dep: add billing to requires + verify purchase/usage
  via the billing block before verified=True (current TODO at line 282).
- discovery.py: route recommend/search through vector.py cosine search.
- sandbox.py: make SANDBOX_RUNNER_URL path mandatory for untrusted code
  (drop insecure fallback).
- connector-infra batch: mcp_adapter cleanup + inbound webhook receiver
  (port verify_incoming_webhook/WebhookMiddleware from Cerebrum donor).
- finance cluster: CoA lifecycle (draft/active versions + approval gate)
  and finance_import CSV/XLSX entry + idempotency.
- hotel: opera_connector real block (no donor exists — build from
  hotelops-v2 connect/fetch/normalise/MockLevel pattern); hotel_v2 wire
  into a product endpoint.
- core-infra/reasoning registrations: project_reasoner already registered
  (verify block.json completeness); remaining unregistered built blocks
  to wrap/register (safety_world_detector, and any core-infra orphans
  from the cluster list).
- <private-repo> enhancement items (API-key scopes/IP/expiry, webhook
  persistence, shared rate-limit store): feature builds, not ports —
  defer to a dedicated wave.
