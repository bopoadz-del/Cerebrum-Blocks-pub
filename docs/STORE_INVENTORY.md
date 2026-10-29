# Store Inventory — verified enumeration

**Verified on 2026-09-23** by a programmatic scan of the Cerebrum-Blocks
checkout (`block_registry/`, `block_store/`, `block_store/kits/`),
`scripts/census_registry.py`, a manifest sweep, and an author
sweep. Every claim below is from the files themselves, not from memory.

## Trust summary

- **Registry blocks advertised** (census). The declarative reasoning kits added 2026-09-24 are all certified. Manifest sweep:
  `block.json` manifests (2026-09-23). Each `block.json` carries a
  `signature` field, but block signing is parked until the publisher registry
  ships: `data/publishers.json` is not in this tree, so no signature here can
  be verified and no block counts as signed (see README, Security). Author sweep: each block
  declares `Cerebrum Team` or no author.
- **Zero stub-like blocks in the Store registry.** The echo-stub pattern
  (`run()` returning `{"status": "ok", "result": <input>}` unconditionally)
  appears nowhere in `block_registry/` (pattern sweep ships in CI). The
  universal_kernel security wave (audit_evidence, provenance_verification)
  contains real SHA-256 chain verification with tamper tests.
- **The five estate blocks are real and registered in the Store**
  (`estate_registry`, `estate_maintenance`, `evidence_verifier`,
  `readiness_engine`, `portfolio_rollup`). The always-ok stubs they
  replaced are gone — Store `main` `9b8d781f`. There is no factory vendor
  mirror of store blocks; the factory consumes this inventory like any
  other client.

### Declarative reasoning kits — 17 verticals

Added 2026-09-24. Each kit is a DECLARATION, not code: `app/blocks/<kit>/manifest.yaml`
is the vocabulary (quantities, qualifier fields, the source-class authority ladder,
state providers, staleness triggers, scope refusals) and `invariants.yaml` is the
records. One shared evaluator (`app/blocks/kit_engine/`) runs them across five hooks —
H0 pre-retrieval, H1 ranking, H2 tool-time, H3 answer-time, H4 export-time — and
knows nothing about any domain.

Block ids are `<kit>_kit`. The five `<kit>_reasoning` blocks built on hand-written
gates are untouched and still published beside them.

All of them are **certified** (three bars, control-delete included). They carry a
`signature` field, but `scripts/verify_block.py` cannot verify it in this tree:
the publisher registry (`data/publishers.json`) is not shipped, so signing is
parked.

**NO INTERVIEW HAS RUN for any of these domains.** Every declared figure value is
null, and each kit reports `interview_status`, `unfilled_figures` and
`unmeasured_invariants` with every answer. All 217 records carry a measurement case — a repeat-probe question, a run count
and a before/after number, most with an over-refusal check — so every kit reports
`ships: true`. The cases are test DESIGNS; running them needs a corpus, which most
of these domains do not have yet.

| Kit | Invariants | Kinds | Declared hooks | Unmeasured |
|---|---|---|---|---|
| aesthetic | 8 | 5 | H1,H3 | 0 |
| airport_construction | 16 | 5 | H1,H2,H3 | 0 |
| architecture | 8 | 4 | H1,H3 | 0 |
| aviation_ops | 15 | 4 | H1,H3 | 0 |
| datacentre | 14 | 9 |  | 0 |
| dental | 8 | 5 | H1,H3 | 0 |
| fire_protection | 21 | 9 |  | 0 |
| fitout | 11 | 4 | H0,H3 | 0 |
| fm | 7 | 5 | H1,H3 | 0 |
| heritage | 7 | 5 | H1,H3 | 0 |
| offshore_marine | 13 | 7 | H0,H2,H3 | 0 |
| og_construction | 13 | 6 | H0,H1,H3 | 0 |
| og_operations | 11 | 6 | H1,H2,H3 | 0 |
| ports_marine | 10 | 4 | H1,H3 | 0 |
| pump_station | 13 | 6 | H1,H2,H3 | 0 |
| rail | 28 | 9 |  | 0 |
| water_treatment | 14 | 5 | H1,H3,H4 | 0 |

## Vertical readiness

### Ready — build and test these nine

| Vertical | Kit | Domain blocks (beyond the generic core) |
|---|---|---|
| hotels | hotel_management | hotel_v2 |
| insurance | insurance | insurance_v2, agency_hierarchy, producer_record, agency_commission_engine, channel_router, attrition_scorer, incentive_targeting, hkia_gn16_rules, bordereaux_ingest, distribution_analytics |
| construction | construction | construction_v2, boq_processor, spec_analyzer, sympy_reasoning, drawing_qto, primavera_parser, smart_orchestrator, jetson_gateway, bim_extractor, bim, learning_engine, recommendation_template, project_reasoner |
| finance | finance, finance_ops | finance_v2, finance_canonical_model, finance_import, finance_data_quality, finance_reconciliation, finance_coa_governance, finance_saas_metrics |
| retail | retail | retail_v2 |
| real estate | real_estate | estate_registry, estate_maintenance, evidence_verifier, readiness_engine, portfolio_rollup (real since `main` `9b8d781f`) |
| legal | legal | legal_v2, legal_knowledge (compliance flags, risk keywords, custom rules) |
| mep coordination | mep_coordination | geometry_engine, clearance_rules, clash_triage, clash_resolver, bcf_export, version_diff, model_clone (registered 2026-09-19; signing parked) |
| marketplaces | marketplace_ops (domain pack) | transaction_state_machine, payment_escrow, task_listing, offer_bidding, review_reputation, task_messaging, dispatch_matching, geolocation_tracking, pricing_surge, dispute_resolution, insurance_compliance, loyalty_referrals, vendor_catalog (certified; signing parked; pack domain-approved 2026-09-23) |

Legal is declared with the honest note: the knowledge layer is
rules-based (compliance flags / risk keywords / custom rules), not an
authoritative legal corpus.

mep_coordination carries a measured acceptance run in the kit
(schependomlaan IFC 49.3MB: 1,437 elements, 14 hard clashes, 399
clearance violations, 287 false positives eliminated, original file
byte-identical after).

The generic core shared by domain kits: `pdf, ocr, chat, image,
formula_executor, formula_executor_v2`. A capability that resolves only to
these (or to cross-cutting plumbing) is flagged as a domain gap at plan
time (2b).

### Excluded — no testing (declared)

medical, veterinary, pharma. Drafts for these verticals carry the
honest note: no authoritative domain content; domain logic would be
fabricated. (Legal was removed from this list on 2026-09-19: `legal_v2`
is registered, real, and tested.)

### Unverified — kit exists, not on the ready list

agriculture, automotive, aviation, education, hr, manufacturing,
oil_gas, supply_chain. Their kits exist in the Store; depth is not
guaranteed until each is declared ready.

## Full kit list (21)

_template (empty) · agriculture · automotive · aviation · construction ·
education · finance · finance_ops · hotel_management · hr · insurance ·
legal · manufacturing · medical · mep_coordination (geometry_engine,
clearance_rules, clash_triage, clash_resolver, bcf_export, version_diff,
model_clone) · oil_gas · pharma · real_estate · retail · supply_chain ·
universal_kernel (identity, authorization_policy, scope_guard,
rate_limit_guard, audit_evidence, provenance_verification,
secure_ingestion, document_parsing, durable_jobs, embedding_provider,
vector_store, hybrid_retrieval, llm_provider, grounded_answer, xlsx_export,
pdf_export, json_audit_export, health, monitoring, structured_outcomes,
billing_entitlement, notification_mailer, approval_action, block_runner)

19 domain kits + `universal_kernel` + `_template`. The previously listed
`universal_business` kit does not exist in `block_store/kits/` and is
removed from this inventory.

## Registry blocks (198) — categories

- **Registered `*_v2` domain blocks (20)**: agriculture_v2, automotive_v2,
  aviation_v2, construction_v2, education_v2, finance_v2,
  formula_executor_v2, hotel_v2, hr_v2, insurance_v2, legal_v2,
  manufacturing_v2, medical_v2, ocr_v2, oil_gas_v2, pdf_v2, pharma_v2,
  real_estate_v2, retail_v2, supply_chain_v2 — every vertical v2 now
  registered; signing parked (the remaining ones were registered 2026-09-20).
- **Unregistered modules (4, by design)**: `document_engine_block` (alias
  shim for the registered `document_engine` package), and the library
  helpers `ifc_loader`, `_knowledge`, `_procedure_routing` — helpers, not
  blocks; the registry counts blocks.
- **Generic core**: pdf, ocr, chat, image, formula_executor(_v2).
- **Cross-cutting plumbing**: database, storage, queue, workflow,
  notification, team, validation, audit, dashboard, analytics, event_bus,
  file_hasher, document_engine, capture, knowledge, memory, search, web,
  email, auth, rate_limiter, cache_manager, monitoring, secrets, skills,
  review, sandbox, orchestration/smart_orchestrator.
- **Governance & security** (universal_kernel): identity,
  authorization_policy, scope_guard, rate_limit_guard, audit_evidence
  (SHA-256 chain — REAL), provenance_verification (digest/root-hash — REAL).
- **Capture/parsing**: drawing_qto, bim_extractor, bordereaux_ingest,
  primavera_parser, spec_analyzer, ocr(_v2), pdf(_v2), image,
  video_metadata_ingest, hkia_gn16_rules.
- **Estate (real)**: estate_registry, estate_maintenance,
  evidence_verifier, readiness_engine, portfolio_rollup.
- **Wave-2 clones (from The_Fork / Steward / FinanceOps / <private-repo>
  donors)**: vdc_clash_detection, vdc_bcf_export, estate_bearer_auth,
  user_auth, multi_tenant_rbac, procore_cde_client.
- **Specialist**: jetson_gateway, sympy_reasoning, learning_engine,
  recommendation_template, project_reasoner, attrition_scorer,
  incentive_targeting, distribution_analytics, agency_commission_engine,
  producer_record, channel_router, finance_canonical_model and the
  finance_ops quality set, mep_coordination clash stack.

## Known defects (tracked, not hidden)

1. `block_store/admin_block.py::_preflight` — the database check reports
   `not_configured` when no database block is bound (honest), but reports
   `ok` without an actual probe when one is injected (PARTIAL — Store
   side, one-line fix queued).

## Consumers of this file

- The factory inventory declaration (`app.factory.inventory`) — ready
  verticals and kit domain sets are mirrored there and enforced at draft
  and plan time.
- Build/test planning: only the eight ready verticals are tested until
  more kits are declared ready.
