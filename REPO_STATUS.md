# Cerebrum Blocks — Repository Status

> **Date:** 2026-09-19  
> **Branch:** feat/cerebrum-reasoning-kernel (verified checkout)  
> **Python files in `app/blocks/`:** 148 (excluding `__init__.py`)  
> **Registered blocks (`block_registry/`):** 198 — all manifested + signed, census 0 missing  
> **Tests collected:** 1944 (0 collection errors)

---

## Summary

Recent merges brought in:
- **FinanceOps foundation blocks** (PR #41): 7 new finance transformation blocks plus container and kit bundle.
- **Generic action-contract runtime** (PR #40): domain-neutral action discovery, registry, and execution engine under `app/blocks/core/action_contract/`.
- **Store registry update** (PR #42): registered `action_contract` in `block_registry/`.

Earlier hygiene pass moved root-level scripts/tests into `scripts/`, `tests/`, and `dev/`; cleaned duplicate PDF dependencies; and wired `tests/test_all_blocks.py` and `tests/test_regression_security.py` into CI.

---

## Block Inventory

| Location | Count |
|----------|-------|
| `app/blocks/*.py` (top-level) | 135 |
| `block_registry/` entries | 115 |
| Containers under `app/containers/` | 2 directories (`construction/`, plus container modules) |
| Core modules under `app/core/` | 40+ |

### Recently added / upgraded blocks

| Block | Purpose | Source | Tier |
|-------|---------|--------|------|
| `universal_kernel` | Product-neutral 24-capability kernel kit (trust, intelligence, operations, frontier) | Mixed (Fork + Factory + new) | **premium** |
| `finance_canonical_model` | Canonical chart-of-accounts and financial data model | FinanceOps kit |
| `finance_coa_governance` | COA governance rules and validation | FinanceOps kit |
| `finance_data_quality` | Financial data quality checks | FinanceOps kit |
| `finance_import` | General ledger and sub-ledger import transforms | FinanceOps kit |
| `finance_reconciliation` | Account reconciliation engine | FinanceOps kit |
| `finance_saas_metrics` | SaaS / subscription KPI calculations | FinanceOps kit |
| `finance_v2` | Composite FinanceOps reasoning block | FinanceOps kit |
| `agency_commission_engine` | Commission calculation and chargebacks | <private-repo> kit |
| `agency_hierarchy` | Agency/producer hierarchy management | <private-repo> kit |
| `attrition_scorer` | Churn / attrition scoring | <private-repo> kit |
| `bordereaux_ingest` | Insurance statement feed ingest | <private-repo> kit |
| `channel_router` | Explainable case channel routing | <private-repo> kit |
| `distribution_analytics` | Distribution performance analytics | <private-repo> kit |
| `hkia_gn16_rules` | HK insurance regulatory rule evaluation | <private-repo> kit |
| `incentive_targeting` | Incentive eligibility and recommendations | <private-repo> kit |
| `producer_record` | Producer / agent record management | <private-repo> kit |

---

## Test Inventory

Collected via `pytest --collect-only`:

```
1944 tests collected in 14.25s (0 collection errors)
```

### Collection errors

None — all 1944 tests collect cleanly (2026-09-19). The previous four
optional-dependency collection errors (`test_vector_search.py`,
`test_web.py`, `test_zvec.py`/sklearn,
`test_formula_executor_v2.py`/RestrictedPython) no longer reproduce.

### CI coverage

`.github/workflows/ci.yml` now runs:

- `tests/integration/`
- `tests/test_typed_block.py`
- `tests/test_all_blocks.py`
- `tests/test_regression_security.py`

---

## Repository Layout

```
├── app/blocks/          # 135 .py files (blocks + helpers)
├── app/containers/      # Domain containers
├── app/core/            # Runtime core
├── app/lib/             # Shared domain libraries
├── dev/                 # Local dev tools (excluded from Docker)
│   └── mock_backend.py
├── scripts/             # Maintenance scripts
│   ├── assemble.py
│   ├── audit_all_blocks.py
│   └── migrate_to_universal.py
├── tests/               # All pytest tests
└── block_store/         # Packaged block archive
```

---

## Known Issues

1. **Optional libraries** — `sklearn`, `RestrictedPython`, and some heavy
   ML packages remain optional; blocks degrade gracefully when absent.
   Test collection is clean (1944 collected, 0 errors, 2026-09-19).
2. **API keys out of credits** — DeepSeek and Anthropic keys need refill.
3. **Optional libraries** — `opencv-python-headless` and some heavy ML packages
   remain optional; blocks degrade gracefully when absent.

---

## Render Deployment

- **Build:** `pip install -r requirements.txt`
- **Start:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **MCP Server:** Mounted at `/mcp`

> Retired from `block_registry/` 2026-09-26: `action_contract` (a library package, `app/blocks/core/action_contract/`, imported directly — it has no block class) and `finance_ops` (a container, `app/containers/finance_ops.py`). Both were manifest-only entries with no runtime the Factory could attach; the code is unchanged.
