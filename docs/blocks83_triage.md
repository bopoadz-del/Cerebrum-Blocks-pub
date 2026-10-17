# P4 — Cerebrum-Blocks PR #83 full-suite triage

**Board freeze:** main stays closed to further feature merges until this table exists.
**This document is the deliverable.** It does not merge #83, does not xfail the suite, and does not change production behavior.

| Field | Value |
|---|---|
| PR | https://github.com/bopoadz-del/Cerebrum-Blocks/pull/83 |
| Branch | `chore/wire-unrun-tests` @ `c962a474` |
| Full-suite job | [run 33196291058 / job 98934156278](https://github.com/bopoadz-del/Cerebrum-Blocks/actions/runs/33196291058/job/98934156278) (2026-08-28T17:47Z) |
| What CI actually checked out | merge `2dbb1135` = `c962a474` into **stale** `main` `f018e134` (K1 / #77) |
| Current `main` (do not revert) | `7c24d355` — trust_tier on `block.json`, pinned to Factory `ACCEPTED_TRUST_TIERS` (#84) |
| Command | `pytest -q tests/` |
| Honest CI count | **4 failed, 1052 passed, 89 skipped, 6 deselected, 3 xfailed, 0 errors** in 44.14s |
| Local claim in the PR / `KNOWN_INCOMPLETE.md` | 20 failed / 1011 passed / 3 errors — **not** the CI number; see §5 |

The first full-suite attempt on this branch ([run 33195828033](https://github.com/bopoadz-del/Cerebrum-Blocks/actions/runs/33195828033)) aborted at collection (`ModuleNotFoundError: bcrypt`) in 5.41s. `c962a474` declared bcrypt; that collection error is closed. The table below is the **second** run — the first honest measurement.

Targeted backend job on the same SHA: **green**. None of the four reds are in that job's explicit file list.

Classes used below:

| Class | Meaning |
|---|---|
| `broken` | Code or test contract is wrong on this SHA; would fail on a correctly provisioned runner |
| `never-wired` | Test asserts a path, corpus, block, or skip-probe that was never installed / never connected |
| `env-dependent` | Needs an optional sibling repo, Redis, live SaaS, or extra env the full-suite job does not provide |
| `already-passing-in-targeted-job` | Failed on someone's laptop; already green in the named backend steps |
| `CI-artifact` | Failure of the job machinery itself (collection abort, missing declared dep), not a product assertion |

Proposed actions are only: **keep red** · **quarantine xfail with reason** · **fix in follow-up**. No silent xfail. `strict=False` xfail is already too close to silent — do not add more of those.

---

## 1. Failed (4) — classify every red

| Test path | Class | Named reason | Proposed action |
|---|---|---|---|
| `tests/core/test_rag_pack_loader.py::test_aviation_core_rag_source_documents_exist` | never-wired | Asserts `block_store/kits/aviation_faa_core_rag/` plus six FAA files (`AIM_Basic_w_Chg_1_2_3_dtd_7-9-26.pdf`, `aim_index.html`, `cfr_part_{61,91,121,135}.xml`). That directory is not in git. The shelf pack `aviation_core_rag` is honest: `fetch_mode=metadata_only`, `ingestion_status.state=not_ingested`, `documents_total=0`. The domain kit that *does* exist is `block_store/kits/aviation`, a different artifact. The other 16 packs have no on-disk corpus check. File is not in the targeted job list. | keep red. Fix in follow-up: either dual-register a licensed FAA corpus kit under that name, or delete/narrow the existence assertion so it matches the metadata-only shelf. Do not xfail silently. |
| `tests/e2e/test_demo_flows.py::test_b3_ingest_then_cited_answer` | broken | Ingest returned 200; sentence-transformers embedded the doc and the query (two `Batches` lines in the log); `/knowledge/ask` returned the exact `_ask_pgvector` empty string (`"I don't have any relevant information in my knowledge base."`) because `search_vectors(..., threshold=0.3)` produced no rows. Same job, same Postgres, same embedder: targeted `tests/core/test_rag_ingestion.py::test_ingest_text_then_retrieve_cited_fact` **passed** with a longer planted aviation fact. B3's one-line SLA sentence (`99.95% monthly uptime`) is below the 0.3 cosine cut. Not a missing `DATABASE_URL` (the skipif did not fire). | keep red. Fix in follow-up: reuse the working planted-truth shape, or retrieve via `hybrid_search` (already thresholds at 0.0 then re-ranks). Do not quarantine until that choice is made. |
| `tests/test_blocks.py::test_monitoring_block` | broken | `MonitoringBlock` default `track_providers` is `["kimi"]` only (`app/blocks/monitoring.py`). The test records deepseek/groq/openai (`_record_call` returns `{"error": "Unknown provider"}` and drops them), then reads `provider_status` for `"deepseek"`. That path returns `{"error": "Unknown provider"}` with no `reliability_score` → `KeyError`. Leaderboard in the same log shows only `kimi`. Contract drift; file never listed in the targeted job. | keep red. Fix in follow-up: point the test at `kimi`, or restore a multi-provider catalog *and* test that. No xfail. |
| `tests/test_e2e.py::TestInfrastructureBlocks::test_cache_manager` | broken | `CacheManagerBlock._redis` is a **method**. Every `if self._redis:` is true (bound method is truthy). `self._redis.setex(...)` is invoked on the method object, raises, and `set()` returns `{"status": "error"}`. The documented in-memory fallback never runs. Missing `@property` (or `self._redis()`). CI has no `REDIS_URL`, but Redis would not save this call path. Class `TestInfrastructureBlocks` is the one e2e class **not** parked behind the legacy skip. | keep red. Fix in follow-up: make `_redis` a property / call the factory; then the no-Redis fallback can pass without adding Redis to CI. |

No collection errors and no pytest `ERROR` rows on this run.

---

## 2. Already-xfailed (3) — named, but not strict

These are the `3 xfailed` in the job summary. They already carry reasons. They are **not** silent, but `strict=False` means a later accidental pass will not fail the job.

| Test path | Class | Named reason | Proposed action |
|---|---|---|---|
| `tests/test_regression_security.py::test_local_drive_rejects_path_outside_data_dir` | broken | Existing xfail: `local_drive` treats leading-slash paths as relative and does not reject them; expectation is outdated. **Already passing in the targeted regression-security step as xfail.** | keep the named xfail until a follow-up either tightens the block or rewrites the expectation. Flip to `strict=True` if quarantining for the full-suite gate. Do not drop the reason. |
| `tests/test_regression_security.py::test_local_drive_rejects_write_op` | broken | Existing xfail: `local_drive` permits safe-path writes; expectation of "not supported" is outdated. Same targeted-job note as above. | same as previous row |
| `tests/test_regression_security.py::test_google_drive_rejects_quote_in_query` | never-wired | Existing xfail: `google_drive` has no `_get_access_token` helper and no quote-rejection logic; test is outdated. | keep named xfail; fix in follow-up or retire the test. `strict=True` if used as a quarantine for #83. |

---

## 3. Skipped-for-cause (89)

CI ran `pytest -q`, so skip names were not printed. The 89 reconstruct exactly from the tree on this SHA:

`77` class-level skips in `tests/test_e2e.py` + `1` live Render skip + `1` module-level skip for `test_xlsx_schedule.py` + `1` module-level skip for `test_regression_construction.py` + `5` cross-repo kernel grounding skips + `4` sandbox-runner-direct skips = **89**.

Module-level `pytest.skip(..., allow_module_level=True)` reports **one** skip per file (the remaining tests are never collected). Those files are still listed by member below so the board can see what never ran.

### 3a. Legacy / never-implemented e2e classes (`tests/test_e2e.py`)

All of these use `pytestmark = pytest.mark.skip(...)`. They are **not** env-dependent.

| Test path | Class | Named reason | Proposed action |
|---|---|---|---|
| `tests/test_e2e.py::TestRegistry::test_registry_loads` | never-wired | `Legacy architecture tests - block/route expectations outdated` | keep skip (named). Do not convert to silent xfail. Rewrite or delete in a dedicated follow-up if the assertions are still wanted. |
| `tests/test_e2e.py::TestRegistry::test_all_poc_blocks_present` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestRegistry::test_no_import_errors` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestRegistry::test_app_routes` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConnectorProtocol::test_base_class_fields` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConnectorProtocol::test_context_key_fallback` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConnectorProtocol::test_construction_blocks_have_context_keys` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConnectorProtocol::test_output_schemas_are_dicts` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConnectorProtocol::test_input_schemas_declare_sources` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConnectorProtocol::test_connector_contract_method` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConnectorProtocol::test_get_stats_includes_context_key` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConnectorRegistry::test_registry_builds` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConnectorRegistry::test_known_edges_present` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConnectorRegistry::test_context_map_unique` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConnectorRegistry::test_pipeline_map_schema_driven` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConnectorRegistry::test_full_poc_pipeline_valid` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConnectorRegistry::test_topology_layers` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConstructionBlocks::test_sympy_reasoning` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConstructionBlocks::test_boq_processor_inline_items` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConstructionBlocks::test_boq_processor_no_input_error` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConstructionBlocks::test_spec_analyzer_text` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConstructionBlocks::test_spec_analyzer_inline_materials` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConstructionBlocks::test_spec_analyzer_no_input_error` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConstructionBlocks::test_drawing_qto_no_file` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConstructionBlocks::test_primavera_parser_no_file` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConstructionBlocks::test_bim_extractor_no_file` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConstructionBlocks::test_historical_benchmark_lookup` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConstructionBlocks::test_historical_benchmark_all_packages` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConstructionBlocks::test_formula_executor` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConstructionBlocks::test_smart_orchestrator_routing` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConstructionBlocks::test_smart_orchestrator_file_routing` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestConstructionBlocks::test_smart_orchestrator_list_actions` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestPoCBlocks::test_heavy_reasoning_cost_variance` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestPoCBlocks::test_heavy_reasoning_grade_mismatch` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestPoCBlocks::test_heavy_reasoning_quantity_mismatch` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestPoCBlocks::test_heavy_reasoning_schedule_delay` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestPoCBlocks::test_heavy_reasoning_safety_flag` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestPoCBlocks::test_heavy_reasoning_summary_kpis` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestPoCBlocks::test_rfi_generator_from_findings` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestPoCBlocks::test_rfi_generator_priority_mapping` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestPoCBlocks::test_rfi_generator_due_dates` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestPoCBlocks::test_rfi_generator_urgent_only_filter` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestPoCBlocks::test_submittal_log_from_boq` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestPoCBlocks::test_submittal_log_categories` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestPoCBlocks::test_submittal_log_deduplication` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestPoCBlocks::test_submittal_log_grade_from_spec` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestReasoningBlocks::test_recommendation_template_variance` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestReasoningBlocks::test_recommendation_template_list_rules` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestReasoningBlocks::test_credibility_scorer` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestReasoningBlocks::test_validator_block` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestReasoningBlocks::test_predictive_engine` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestReasoningBlocks::test_evidence_vault_store_and_retrieve` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestIntelligentWorkflow::test_parallel_execution` | never-wired | `IntelligentWorkflowBlock not implemented` | keep skip. Implement the block or delete the class in a follow-up. |
| `tests/test_e2e.py::TestIntelligentWorkflow::test_schema_driven_context_keys` | never-wired | class skip **and** method skip `Legacy orchestrator context expectations` | same |
| `tests/test_e2e.py::TestIntelligentWorkflow::test_execution_summary` | never-wired | `IntelligentWorkflowBlock not implemented` | same |
| `tests/test_e2e.py::TestIntelligentWorkflow::test_missing_block_handled` | never-wired | class skip **and** method skip `Legacy orchestrator context expectations` | same |
| `tests/test_e2e.py::TestIntelligentWorkflow::test_no_steps_returns_error` | never-wired | `IntelligentWorkflowBlock not implemented` | same |
| `tests/test_e2e.py::TestFullPipeline::test_poc_pipeline_all_stages` | never-wired | `Legacy architecture tests - block/route expectations outdated` | keep skip |
| `tests/test_e2e.py::TestFullPipeline::test_pipeline_cost_impact_math` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestFullPipeline::test_intelligent_workflow_auto_reason` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestContainers::test_construction_container` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestContainers::test_security_container_create_key` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestContainers::test_ai_core_container_leaderboard` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestContainers::test_store_container_stats` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestContainers::test_ml_container` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestContainers::test_reasoning_engine_container` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestMLEngine::test_ml_engine_train_predict` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestMLEngine::test_learning_engine` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestAPIEndpoints::test_health_endpoint` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestAPIEndpoints::test_blocks_list_endpoint` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestAPIEndpoints::test_poc_health_endpoint` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestAPIEndpoints::test_poc_topology_endpoint` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestAPIEndpoints::test_poc_validate_pipeline_endpoint` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestAPIEndpoints::test_poc_analyze_full_pipeline` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestAPIEndpoints::test_poc_analyze_credibility_not_silent_fallback` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestAPIEndpoints::test_execute_endpoint_boq` | never-wired | same class skip | same |
| `tests/test_e2e.py::TestAPIEndpoints::test_historical_benchmark_pipeline_format` | never-wired | same class skip | same |

### 3b. Live Render

| Test path | Class | Named reason | Proposed action |
|---|---|---|---|
| `tests/test_api_live.py::test_execute_construction` | env-dependent | `Live Render API — construction optional on virgin CB deployments`. Hits `https://ssdppg.onrender.com`. (`test_health` / `test_blocks_list` in the same file are **not** skipped and ran.) | keep the named skip. Do not xfail. Do not put live credentials in CI. |

### 3c. Construction skip-probe looks at the old single-file path

`tests/conftest.py` sets `CONSTRUCTION_CONTAINER_PATH = <repo>/app/containers/construction.py`. Construction is a **package** (`app/containers/construction/__init__.py`) on both the #83 branch and current main. `.py` does not exist, so these two modules skip at import even though B6 (`tests/e2e/test_demo_flows.py::test_b6_construction_document_extraction`) imported the package and **passed** in this same job.

CI reports each file as **one** skip. Members that never collected:

| Test path | Class | Named reason | Proposed action |
|---|---|---|---|
| `tests/test_xlsx_schedule.py` (module; 7 tests not collected: `test_parse_xlsx_schedule_happy_path`, `test_parse_xlsx_schedule_no_schedule_sheet`, `test_parse_xlsx_schedule_multi_sheet_picks_correct_sheet`, `test_parse_xlsx_schedule_datetime_cell_values`, `test_parse_primavera_schedule_dispatches_xlsx`, `test_classify_document_detects_xlsx_schedule_by_sheet_shape`, `test_classify_document_detects_xlsx_schedule_by_filename`) | never-wired | Skip probe requires `app/containers/construction.py`. Package is `app/containers/construction/`. Reason string: `Construction kit not installed — run store install or copy from bundle/`. That reason is stale. | keep red/skip until follow-up retargets the probe at the package (`construction/__init__.py` or the directory). Then these become runnable. No xfail. |
| `tests/test_regression_construction.py` (module; tests not collected include `test_safe_float_*`, `test_parse_money_str[*]`, `test_extract_financial_terms_*`, `test_extract_obligations_semicolon_terminator`, `test_lookup_unit_cost_*`, `test_create_submittal_item_status_matches_spa_enum`, `test_auto_pipeline_*`) | never-wired | Same stale `construction.py` probe. | same |

### 3d. Cross-repo kernel (CI does not check out <private-repo>)

These call `_product_with_kernel()`, which skips when `CEREBRUM_KERNEL_SRC` is unset and `../<private-repo>/backend/app/cerebrum_product_kernel` is absent. The file's own docstring says this is CI's situation. Block-level tests in the same file **passed**.

| Test path | Class | Named reason | Proposed action |
|---|---|---|---|
| `tests/test_grounding_end_to_end.py::test_the_real_kernel_set_loads_in_a_generated_product` | env-dependent | `the product kernel is not checked out beside this repo; set CEREBRUM_KERNEL_SRC to run the cross-repo grounding proof` | keep skip. Optional follow-up: a CI job that checks out the sibling kernel. Do not xfail. |
| `tests/test_grounding_end_to_end.py::test_a_real_base_definition_grounds_with_its_real_provenance` | env-dependent | same | same |
| `tests/test_grounding_end_to_end.py::test_an_overlay_definition_outranks_nothing_and_reports_its_own_tier` | env-dependent | same | same |
| `tests/test_grounding_end_to_end.py::test_the_other_two_states_hold_against_the_real_set[work out the customer lifetime value-model_generated]` | env-dependent | same | same |
| `tests/test_grounding_end_to_end.py::test_the_other_two_states_hold_against_the_real_set[calculate 10 * 8 * 0.2-user_specified]` | env-dependent | same | same |

### 3e. Sandbox runner-direct TestClient (deadlock guard)

Fixture `runner_client` skips unless `SANDBOX_RUNNER_DIRECT_TESTS=1` (deadlocks with the main-app TestClient in the same process). Other tests in `test_sandbox_runner_client.py` ran (Linux; the win32 `resource` skipif did not fire).

| Test path | Class | Named reason | Proposed action |
|---|---|---|---|
| `tests/test_sandbox_runner_client.py::test_runner_health_endpoint` | env-dependent | `Runner-direct TestClient tests deadlock with main-app TestClient in the same process. Set SANDBOX_RUNNER_DIRECT_TESTS=1 to enable.` | keep skip in the combined full-suite job. Follow-up: a separate job that sets the flag and does not import the main-app TestClient. |
| `tests/test_sandbox_runner_client.py::test_runner_exec_python_returns_result` | env-dependent | same | same |
| `tests/test_sandbox_runner_client.py::test_runner_exec_rejects_empty_code` | env-dependent | same | same |
| `tests/test_sandbox_runner_client.py::test_runner_exec_python_uses_input_values` | env-dependent | same | same |

---

## 4. Deselected (6) — pytest.ini `-m "not requires_local_registry and not mlflow and not manual_script"`

Not failures. Listed so the board sees what the full-suite job still refuses to ask.

| Test path | Class | Named reason | Proposed action |
|---|---|---|---|
| `tests/test_mlflow_tracker.py::test_real_backend_round_trip` | env-dependent | marker `mlflow` — live MLflow backend, skipped by default | keep deselected. Separate optional job if wanted. |
| `tests/integration/test_kit_connector_e2e.py::test_construction_not_in_app_blocks` | env-dependent | marker `requires_local_registry` — `data/domain_kit_registry.json` / machine-local kit state | keep deselected |
| `tests/integration/test_kit_connector_e2e.py::test_virgin_boot_flag` | env-dependent | same marker | keep deselected |
| `tests/integration/test_kit_connector_e2e.py::test_install_medical_skeleton_registers_connector` | env-dependent | same marker | keep deselected |
| `tests/integration/test_kit_connector_e2e.py::test_store_lists_required_kits` | env-dependent | same marker | keep deselected |
| `tests/integration/test_kit_connector_e2e.py::test_coming_soon_kits_have_connectors` | env-dependent | same marker | keep deselected |

---

## 5. Local-only reds that did **not** reproduce in CI

Do not quarantine from the PR author's laptop count. The PR text already named these; CI contradicted them.

| Local claim | What CI did | Class if someone files it anyway | Action |
|---|---|---|---|
| `tests/core/test_registry_integrity.py` failed locally | Passed in the targeted backend job **and** in full-suite | already-passing-in-targeted-job | ignore; missing local dep, not a defect |
| `tests/core/test_block_contracts.py` failed locally | same | already-passing-in-targeted-job | ignore |
| `tests/test_kit_composition_audit.py` / `universal_business :: no_manifest` | Cannot occur: untracked directory, not in git | CI-artifact (author workspace) | ignore |
| 3 errors in `tests/core/test_rag_planted_truth.py` (embedding / sklearn) | Passed in full-suite (`sentence-transformers` / `scikit-learn` are in `requirements.txt`) | already-passing-in-targeted-job / env-dependent on the laptop | ignore |
| First CI run: collection `No module named 'bcrypt'` | Fixed on the branch by `c962a474` (`bcrypt` in `requirements.txt`) | CI-artifact (undeclared dep; closed) | already fixed; do not re-open |

---

## 6. Rebase note vs current main `7c24d355` (#84)

#83's merge base in the published log is `f018e134`. Main has since taken K3/K4/K6/K7/grounding (#78–#82) and **trust_tier (#84)**. #84 is in force and must not be reverted.

Rebase of `chore/wire-unrun-tests` onto `7c24d355` will add at least:

- `app/core/trust_tier.py` + `tests/core/test_trust_tier_manifest.py`
- `trust_tier` on every `block_registry/**/block.json`
- targeted CI step for that pin (`.github/workflows/ci.yml` on main already lists extra files #83's copy of the workflow does not, e.g. `tests/test_kit_bundle_freshness.py`)

This table does **not** invent #84 failures. After rebase, re-run `pytest -q tests/` once and append any **new** reds. Do not merge #83 green by guessing.

Insurance / P6 files were not opened.

---

## 7. What not to do

- Do not merge #83 while the full-suite job is a required gate and these four reds are unclassified follow-ups.
- Do not pre-emptively xfail the four reds, the 77 legacy skips, or the world.
- Do not treat the local `20 / 1011 / 3` as the board number.
- Do not revert #84 to make a rebase look smaller.

If the board later wants the full-suite job green *without* product fixes, the only acceptable quarantine is an `xfail(strict=True, reason="<the named reason in this table>")` on a **named** row, in a follow-up PR, not in #83's first landing.

---

## 8. Counts for FLEET_OPS

| Bucket | N | Disposition |
|---|---|---|
| Failed | 4 | 3 broken + 1 never-wired; all keep red; all fix-in-follow-up |
| Errors | 0 (latest run) | first-run bcrypt collection error already fixed on branch |
| Xfailed | 3 | named reasons already; tighten to `strict=True` if used as quarantine |
| Skipped-for-cause | 89 | 77 never-wired legacy e2e + 1 live Render + 2 stale construction probes + 5 kernel-sibling + 4 sandbox-direct |
| Deselected | 6 | markers; keep |
| Passed | 1052 | including every targeted-job file |
| Local-only reds | (not in CI) | do not act |
