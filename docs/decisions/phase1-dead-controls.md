# Phase 1 — Dead-control dispositions (Cerebrum-Blocks)

Rule applied: a control that exists but is not on the live path is either
WIRED into the live path or DELETED along with every claim about it.
There is no third state.

| Control | Location | Decision | Live path now |
| --- | --- | --- | --- |
| `validate_shelf` (virgin shelf) | `app/core/virgin_shelf.py` | **WIRED** | `load_shelf` validates by default and raises `VirginShelfError` on an invalid shelf; `validate_shelf` remains as the reporting form. Test: `test_load_shelf_fails_closed_on_invalid_shelf`. |
| `validate_shelf` (source packs) | `app/core/source_pack_loader.py` | **WIRED** | Same pattern; `SourcePackError` on invalid shelf. |
| `validate_shelf` (RAG packs) | `app/core/rag_pack_loader.py` | **WIRED** | Same pattern; `RagPackLoaderError` on invalid shelf. |
| `validate_transition` | `app/blocks/_knowledge.py` | **WIRED** | Exposed as the `validate_transition` action on the `construction_advisor` block, reachable via `/v1/execute`. The three procurement workflow entries in the construction KB are now callable. Tests: `tests/blocks/test_construction_advisor_transitions.py`. |
| `verify_kit` | `block_store/kits/universal_kernel/wave1/provenance_verification` | **WIRED** | `install_kit` (the store's live install path, `POST /containers/{kit_id}/install`) verifies `provenance.json` when present and refuses tampered kits; a kit without a provenance manifest installs with `provenance: "absent — unverified"` in the response — nothing is silently assumed verified. Populating manifests for all kits is Phase 5 (block signing). Tests: `tests/core/test_container_kit_provenance.py`. |
| `verify_token` | `block_store/kits/universal_kernel/wave1/identity` | **INVENTORY — not a platform control** | The Wave-1 brief defines these kits as "versioned libraries consumed via the Store, not deployed services"; no platform doc claims identity guards platform traffic (checked README, API.md, REPO_STATUS.md, PARKED_BLOCKERS.md), so there is no false claim to delete. The platform's own live auth is the API-key manager. The kit stays as store inventory exercised by its certification test (`tests/universal_kernel/test_trust_chain.py`). If the owner rules this a third state, the alternative is deleting the identity kit from the store — a product decision not taken unilaterally here. |
| schema_registry validators | `app/core/schema_registry.py` | **DELETED** | The four exported convenience validators (`validate_text_content`, `validate_image_content`, `validate_pdf_content`, `validate_chat_message`) had no callers outside tests and were removed. The registry's *type schemas* stay: they are the block `input_schema`/`output_schema` dicts enforced live (and now fail-closed) by `TypedBlock.execute`. |

<private-repo> dispositions (`assert_host_allowed`, `validate_dna_document`,
`assert_not_executable`, `validate_index`) are recorded in the same file name
in that repository.
