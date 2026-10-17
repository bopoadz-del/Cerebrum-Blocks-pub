# KNOWN_INCOMPLETE — Cerebrum-Blocks

Honest roadmap of functions that are intentionally not fully implemented in the
shipping `app/` tree. Each is off every documented demo flow (see the e2e
suite). `scripts/audit_stubs.py` reads the `path :: name` keys below and treats
them as registered, so a green audit still surfaces anything NEW.

Format: `- <path> :: <name>  — <reason>`

## Optional base-class hooks (correct defaults; overridden per domain)
- app/containers/base.py :: get_rag_filters  — optional domain filter hook; `None` = no filter (search all) is the correct default. Overridden by domains that scope RAG.
- app/core/universal_base.py :: route  — overridable base; `process()` provides the real action routing. Containers that need custom routing override it.
- app/blocks/recommendation_template.py :: __missing__  — dict-subclass fallback hook (template placeholder resolution).

## Construction container — Fork-parity extraction (ROADMAP, not a ship blocker)
Per the completion spec, deep construction extraction to Fork parity is roadmap.
The primary document/drawing ingest happy path is covered by the demo flow; the
advanced/secondary extractors below are deferred and must NOT return faked data.
- app/containers/construction/__init__.py :: _extract_tables_advanced  — advanced table reconstruction beyond the primary parser; roadmap.
- app/containers/construction/__init__.py :: _extract_annotations  — drawing annotation extraction; roadmap.
- app/containers/construction/__init__.py :: _extract_title_block  — drawing title-block parsing; roadmap.
- app/containers/construction/__init__.py :: _extract_equipment_from_photos  — vision equipment detection; roadmap.
- app/containers/construction/__init__.py :: _extract_quality_observations  — QA observation mining; roadmap.
- app/containers/construction/__init__.py :: _extract_material_deliveries  — delivery-log extraction; roadmap.
- app/containers/construction/__init__.py :: _identify_resource_conflicts  — schedule resource-conflict detection; roadmap.
- app/containers/construction/__init__.py :: _identify_qualification_gaps  — prequalification gap analysis; roadmap.
- app/containers/construction/__init__.py :: _identify_bid_clarifications  — bid clarification mining; roadmap.
- app/containers/construction/__init__.py :: _identify_consolidation  — procurement consolidation; roadmap.
- app/containers/construction/__init__.py :: _suggest_bundling  — package bundling suggestions; roadmap.
- app/containers/construction/__init__.py :: _identify_procurement_risks  — procurement risk mining; roadmap.
- app/containers/construction/__init__.py :: _map_system_dependencies  — commissioning dependency mapping; roadmap.
- app/containers/construction/__init__.py :: _generate_daily_tasks  — maintenance schedule generation; roadmap.
- app/containers/construction/__init__.py :: _generate_weekly_tasks  — maintenance schedule generation; roadmap.
- app/containers/construction/__init__.py :: _generate_quarterly_tasks  — maintenance schedule generation; roadmap.
- app/containers/construction/__init__.py :: _create_maintenance_matrix  — maintenance matrix build; roadmap.
- app/containers/construction/__init__.py :: _generate_troubleshooting_guide  — O&M troubleshooting; roadmap.
- app/containers/construction/__init__.py :: _generate_spare_parts_list  — spare-parts extraction; roadmap.
- app/containers/construction/__init__.py :: _extract_training_needs  — training needs extraction; roadmap.

## Domain kit extractors (roadmap; kits ship with the primary path only)
- app/blocks/finance_v2.py :: _extract_cash_flows  — advanced cash-flow extraction; roadmap.
- app/blocks/finance_v2.py :: _extract_returns  — advanced returns extraction; roadmap.
- app/blocks/medical_v2.py :: _phi_context  — PHI-context helper; roadmap.
- app/blocks/migration.py :: _restore_backup  — migration restore helper (backup/restore path uses core/backup.py); roadmap.
- app/blocks/document_engine/parsers/pdf_parser.py :: _blocks_to_tables  — PDF block→table reconstruction; primary text path works, table reconstruction is roadmap.

## universal_kernel neutral-kit templates (off every demo flow B1-B6)
The universal_kernel kit ships neutral provider templates; the `hash` embedding
provider is the real default. The main app runtime does handler security via
`app/core/block_validation.py` (AST scan + signature), not this kit runner.
- block_store/recommendation_template.py :: __missing__  — dict fallback hook.
- block_store/kits/universal_kernel/wave1/rate_limit_guard/code.py :: reset  — test/reset helper.
- block_store/kits/universal_kernel/wave2/embedding_provider/code.py :: embed  — OpenAI provider stub; raises NotImplementedError honestly. Default is HashEmbeddingProvider.
- block_store/kits/universal_kernel/wave2/llm_provider/code.py :: complete  — the OpenAI provider is still a stub (raises NotImplementedError honestly); the kit's real provider is `KimiProvider` (Moonshot, live over the OpenAI-compatible API) via `get_provider("kimi")`.
- block_store/kits/universal_kernel/wave4/block_runner/code.py :: _check_handler_security  — neutral-kit runner hook; the shipping runtime validates handlers in app/core/block_validation.py.

- block_store/kits/automotive :: `evaluation/` — declared as an install artifact and as `data` by #64, but never authored: absent at the kit root and in `bundle/`. Install raised `ContainerKitError("bundle incomplete")` while the store listed the kit `available`. Removed from `artifacts` and `data` so the manifest stops claiming a path that does not exist. `rag.evaluation` still names `evaluation/golden_questions.jsonl` as the intended eval set — that is a statement of intent for the kit author (pipeline stage K6), not an existence claim the installer checks. Restore both when the eval is written.

- .github/workflows/ci.yml :: **the backend job's explicit file list**. It names 25 of this repository's 134 test files; the other 103 never executed, so a new test file passed by never being asked — which is how a bundle-completeness fence went green on its own PR without running. A `full-suite` job now runs `tests/` whole. The targeted list is kept rather than deleted: it is fast, it fails with an attributable name, and removing it would lose that. Measured locally before wiring (with two files skipped for a missing `sklearn`): **1011 passed, 20 failed, 101 skipped, 3 errors**. Several of those failures are local-environment artifacts — `test_registry_integrity.py` and `test_block_contracts.py` are already in the backend list and pass in CI — so that local number is not the CI count. The first honest CI measurement is recorded in `docs/blocks83_triage.md` (#86): **4 failed, 1052 passed, 89 skipped, 3 xfailed**.

- block_store/kits/construction, block_store/kits/insurance :: **not reproducible from source**. Both were published from The_Fork. 2 of construction's 42 declared artifacts and 6 of insurance's 29 are authored in neither this repo nor the current Fork checkout (`app/containers/construction.py`, `app/data/procedures/procedures_db.json`, `app/data/gn16_ruleset.json`, `app/knowledge/hkia_gn16_corpus.json`, the four `app/playbooks/*.json`) — `bundle/` holds the only copy. Losing a bundle file loses the content. `publish_kit.py --domain <kit> --refresh` keeps their shared platform code current and reports the orphans; a full republish is impossible until the sources are recovered or re-authored.

- block_store/kits/insurance/parked :: six uncited data files (`commission_formulas.json`, `hierarchy_model.json`, `incentive_playbook.json`, `retention_playbook.json`, `routing_sops.json`, `sample_bordereaux.json`) ran through `scripts/intake_formulas.py --kind contributor_unverified`. They were bundle-only orphans with no checkable source; inventing an HKIA/regulator cite would have been worse than the blank. Parked outside declared `data`, so no engine loads them. Re-run intake with a checkable `--kind` to ship. `publish_kit.py --refresh` cannot republish them: they are not declared artifacts.

- app/blocks/agency_commission_engine.py :: EMBEDDED_FORMULAS  — the same uncited rate table as the parked JSON. After parking, this is the copy the engine loads (formula_source=`embedded`). It is not a sourced table and is not a regulator cite. Verify through intake and point `formula_path` at a checkable file before treating these rates as declared data.
