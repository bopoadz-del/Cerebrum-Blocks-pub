"""Foundation tests for the FinanceOps Store kit."""

import pytest

from app.blocks.finance_canonical_model import FinanceCanonicalModelBlock
from app.blocks.finance_coa_governance import FinanceCoAGovernanceBlock
from app.blocks.finance_data_quality import FinanceDataQualityBlock
from app.blocks.finance_import import FinanceImportBlock
from app.blocks.finance_reconciliation import FinanceReconciliationBlock
from app.blocks.finance_saas_metrics import FinanceSaaSMetricsBlock


@pytest.mark.asyncio
async def test_canonical_model_exposes_governed_contract():
    out = await FinanceCanonicalModelBlock().process({"operation": "schema"})
    assert out["status"] == "success"
    assert "entity_id" in out["dimensions"]
    assert "gl_entry" in out["fact_types"]
    assert out["money_serialization"] == "fixed_point_string_4dp"
    assert len(out["schema_digest"]) == 64


@pytest.mark.asyncio
async def test_gl_import_derives_decimal_amount_and_period():
    out = await FinanceImportBlock().process({
        "source_type": "gl", "source_system": "erp",
        "rows": [{
            "line_id": "L1", "voucher_id": "V1", "legal_entity": "IFS",
            "gl_account": "4000", "fiscal_period": "202607",
            "currency_code": "usd", "debit": "125.10", "credit": "25.10",
        }],
    })
    assert out["status"] == "success"
    row = out["accepted"][0]
    assert row["period"] == "2026-07"
    assert row["currency"] == "USD"
    assert row["amount"] == "100.0000"


@pytest.mark.asyncio
async def test_import_rejects_missing_required_account():
    out = await FinanceImportBlock().process({
        "source_type": "gl",
        "rows": [{
            "line_id": "L1", "legal_entity": "IFS", "fiscal_period": "2026-07",
            "currency_code": "USD", "debit": 100, "credit": 0,
        }],
    })
    assert out["status"] == "validation_error"
    assert any(issue.get("field") == "account_id" for issue in out["rejected"][0]["issues"])


@pytest.mark.asyncio
async def test_data_quality_detects_duplicate_and_unbalanced_voucher():
    records = [
        {"record_type": "gl_entry", "record_id": "1", "source_record_id": "V1", "entity_id": "IFS", "account_id": "4000", "period": "2026-07", "currency": "USD", "amount": "100.0000"},
        {"record_type": "gl_entry", "record_id": "1", "source_record_id": "V1", "entity_id": "IFS", "account_id": "1000", "period": "2026-07", "currency": "USD", "amount": "-90.0000"},
    ]
    out = await FinanceDataQualityBlock().process({"records": records})
    assert out["status"] == "validation_error"
    codes = {issue["code"] for issue in out["issues"]}
    assert {"duplicate_key", "journal_unbalanced"} <= codes


@pytest.mark.asyncio
async def test_reconciliation_honours_decimal_tolerance():
    left = [{"entity_id": "IFS", "account_id": "4000", "period": "2026-07", "currency": "USD", "amount": "100.0050"}]
    right = [{"entity_id": "IFS", "account_id": "4000", "period": "2026-07", "currency": "USD", "amount": "100.0000"}]
    within = await FinanceReconciliationBlock().process({"left_records": left, "right_records": right, "tolerance": "0.01"})
    outside = await FinanceReconciliationBlock().process({"left_records": left, "right_records": right, "tolerance": "0.001"})
    assert within["reconciliation_status"] == "reconciled"
    assert outside["reconciliation_status"] == "exceptions"
    assert outside["variances"][0]["variance"] == "0.0050"


@pytest.mark.asyncio
async def test_coa_validation_detects_cycle_unmapped_and_missing_approver():
    out = await FinanceCoAGovernanceBlock().process({
        "operation": "validate",
        "current_accounts": [{"account_id": "1000"}, {"account_id": "2000"}],
        "proposed_accounts": [
            {"account_id": "1100", "parent_id": "2100"},
            {"account_id": "2100", "parent_id": "1100"},
        ],
        "mappings": [{
            "old_account_id": "1000", "new_account_id": "1100",
            "effective_from": "2026-01-01", "status": "approved",
        }],
    })
    assert out["status"] == "validation_error"
    codes = {issue["code"] for issue in out["issues"]}
    assert {"account_hierarchy_cycle", "active_account_unmapped", "approved_mapping_missing_approver"} <= codes


@pytest.mark.asyncio
async def test_coa_impact_analysis_traces_dependencies():
    out = await FinanceCoAGovernanceBlock().process({
        "operation": "impact_analysis",
        "changed_account_ids": ["4000"],
        "dependencies": [
            {"dependency_id": "board-pack", "type": "report", "account_ids": ["4000"]},
            {"dependency_id": "cash-model", "type": "model", "account_ids": ["1000"]},
        ],
    })
    assert out["status"] == "success"
    assert out["impact_count"] == 1
    assert out["impacted_dependencies"][0]["dependency_id"] == "board-pack"


@pytest.mark.asyncio
async def test_saas_metrics_normalize_monthly_and_annual_values():
    out = await FinanceSaaSMetricsBlock().process({
        "operation": "calculate", "as_of": "2026-07-31",
        "contracts": [
            {"contract_id": "C1", "customer_id": "A", "start_date": "2026-01-01", "term_months": 12, "billing_frequency": "monthly", "recurring_amount": "1000", "currency": "USD"},
            {"contract_id": "C2", "customer_id": "B", "start_date": "2026-01-01", "term_months": 12, "billing_frequency": "annual", "recurring_amount": "12000", "currency": "USD"},
        ],
    })
    assert out["status"] == "success"
    assert out["totals"]["mrr"] == "2000.0000"
    assert out["totals"]["arr"] == "24000.0000"
    assert out["totals"]["tcv"] == "24000.0000"


@pytest.mark.asyncio
async def test_saas_metrics_refuse_hidden_fx_aggregation():
    out = await FinanceSaaSMetricsBlock().process({
        "operation": "calculate", "as_of": "2026-07-31",
        "contracts": [
            {"contract_id": "C1", "customer_id": "A", "start_date": "2026-01-01", "term_months": 12, "mrr": "100", "currency": "USD"},
            {"contract_id": "C2", "customer_id": "B", "start_date": "2026-01-01", "term_months": 12, "mrr": "100", "currency": "EUR"},
        ],
    })
    assert out["status"] == "dependency_required"
    assert out["currencies"] == ["EUR", "USD"]


@pytest.mark.asyncio
async def test_arr_bridge_calculates_nrr_and_grr():
    out = await FinanceSaaSMetricsBlock().process({
        "operation": "bridge", "opening_arr": "100", "new_arr": "10",
        "expansion_arr": "5", "contraction_arr": "2", "churn_arr": "3",
    })
    assert out["closing_arr"] == "110.0000"
    assert out["nrr_pct"] == "100.00"
    assert out["grr_pct"] == "95.00"
    assert out["control_check"]["balanced"] is True


@pytest.mark.asyncio
async def test_mapping_resolution_requires_one_approved_effective_mapping():
    out = await FinanceCoAGovernanceBlock().process({
        "operation": "resolve_mapping", "old_account_id": "4000", "as_of": "2026-07-01",
        "mappings": [{"old_account_id": "4000", "new_account_id": "4100", "effective_from": "2026-01-01", "status": "proposed"}],
    })
    assert out["status"] == "dependency_required"
    assert out["candidate_count"] == 0
