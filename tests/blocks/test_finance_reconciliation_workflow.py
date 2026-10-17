"""Finance reconciliation workflow â€” ported <private-repo>
reconciliation/service.py run/exception state machine (in-process store)."""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.blocks.finance_reconciliation_workflow import (
    FinanceReconciliationWorkflowBlock,
    _variance_exceeds_tolerance,
)


def _run(coro):
    return asyncio.run(coro)


def _p(b, payload):
    return _run(b.process(payload))


def _mk_run(b, run_type="actuals_vs_budget", tenant="t1"):
    return _p(b, {"action": "create_run", "tenant_id": tenant, "run_type": run_type, "source_period": "2026-01"})


def _rec(account_id, amount, legal="", period="2026-01", currency="USD"):
    return {"account_id": account_id, "legal_entity_id": legal, "period": period, "currency_code": currency, "amount": amount}


# -- run lifecycle -------------------------------------------------------------

def test_invalid_run_type_fails_loud():
    b = FinanceReconciliationWorkflowBlock()
    r = _p(b, {"action": "create_run", "tenant_id": "t1", "run_type": "guess", "source_period": "2026-01"})
    assert r["status"] == "error"
    assert "Invalid run_type" in r["error"]


def test_unsupported_run_types_fail_the_run_honestly():
    b = FinanceReconciliationWorkflowBlock()
    for run_type in ("bank_vs_ledger", "intercompany"):
        r = _mk_run(b, run_type=run_type)
        run_id = r["result"]["run"]["id"]
        pr = _p(b, {"action": "process_run", "run_id": run_id})
        assert pr["status"] == "refused"
        assert f"Run type {run_type} not supported by honest reconciliation" in pr["error"]
        run = _p(b, {"action": "get_run", "run_id": run_id, "tenant_id": "t1"})
        assert run["result"]["run"]["status"] == "failed"


def test_completed_run_cannot_be_reprocessed():
    b = FinanceReconciliationWorkflowBlock()
    r = _mk_run(b)
    run_id = r["result"]["run"]["id"]
    _p(b, {"action": "set_run_data", "run_id": run_id, "actuals": [_rec("a1", "100")], "plans": [_rec("a1", "100")]})
    first = _p(b, {"action": "process_run", "run_id": run_id})
    assert first["status"] == "ok"
    assert first["result"]["run"]["status"] == "completed"
    second = _p(b, {"action": "process_run", "run_id": run_id})
    assert second["status"] == "refused"
    assert "Cannot process run in status completed" in second["error"]


# -- tolerance math (donor _variance_exceeds_tolerance) ------------------------

def test_variance_exceeds_tolerance_rules():
    d = Decimal("5.00")
    assert _variance_exceeds_tolerance(d, Decimal("10"), None, Decimal("100")) is False
    assert _variance_exceeds_tolerance(d, Decimal("1"), None, Decimal("100")) is True
    assert _variance_exceeds_tolerance(d, None, Decimal("3"), Decimal("100")) is True  # 5 > 3% of 100
    assert _variance_exceeds_tolerance(d, None, Decimal("10"), Decimal("100")) is False
    # Default tolerance when no rule is configured.
    assert _variance_exceeds_tolerance(Decimal("0.02"), None, None, Decimal("100")) is True
    assert _variance_exceeds_tolerance(Decimal("0.005"), None, None, Decimal("100")) is False


# -- exceptions + dedup ----------------------------------------------------------

def test_process_run_flags_amount_mismatch_against_tolerance_rule():
    b = FinanceReconciliationWorkflowBlock()
    r = _mk_run(b)
    run_id = r["result"]["run"]["id"]
    _p(b, {"action": "create_match_rule", "tenant_id": "t1", "name": "strict", "tolerance_amount": "1.00"})
    _p(b, {"action": "set_run_data", "run_id": run_id,
           "actuals": [_rec("a1", "105.00")], "plans": [_rec("a1", "100.00")]})
    pr = _p(b, {"action": "process_run", "run_id": run_id})
    assert pr["status"] == "ok"
    assert pr["result"]["run"]["variance_amount"] == "5.00"
    exc = pr["result"]["exceptions"]
    assert any(e["exception_type"] == "amount_mismatch" for e in exc)


def test_missing_record_exceptions_for_plan_only_and_actual_only():
    b = FinanceReconciliationWorkflowBlock()
    r = _mk_run(b)
    run_id = r["result"]["run"]["id"]
    _p(b, {"action": "set_run_data", "run_id": run_id,
           "actuals": [_rec("a1", "100"), _rec("a3", "7")],
           "plans": [_rec("a1", "100"), _rec("a2", "50")]})
    pr = _p(b, {"action": "process_run", "run_id": run_id})
    assert pr["status"] == "ok"
    kinds = {e["exception_type"]: e for e in pr["result"]["exceptions"]}
    assert "missing_record" in kinds
    assert pr["result"]["run"]["status"] == "completed"


def test_ensure_exception_dedup_is_idempotent():
    """Reprocessing the same diff path must not duplicate open exceptions."""
    b = FinanceReconciliationWorkflowBlock()
    r = _mk_run(b)
    run_id = r["result"]["run"]["id"]
    _p(b, {"action": "set_run_data", "run_id": run_id,
           "actuals": [_rec("a1", "105.00")], "plans": [_rec("a1", "100.00")]})
    pr = _p(b, {"action": "process_run", "run_id": run_id})
    first_count = pr["result"]["open_exception_count"]
    # Re-running the merge path directly on the same run must not add new rows.
    run = _p(b, {"action": "get_run", "run_id": run_id, "tenant_id": "t1"})["result"]["run"]
    b._ensure_exception(run, "a1", "amount_mismatch", "error", Decimal("100"), Decimal("105"), Decimal("5"), "dup")
    after = _p(b, {"action": "list_exceptions", "run_id": run_id, "tenant_id": "t1"})
    assert after["result"]["count"] == first_count


def test_block_report_merges_variances_into_exceptions():
    """The Store finance_reconciliation block's variances are merged + deduped."""
    b = FinanceReconciliationWorkflowBlock()
    r = _mk_run(b)
    run_id = r["result"]["run"]["id"]
    _p(b, {"action": "set_run_data", "run_id": run_id,
           "actuals": [_rec("a1", "100"), _rec("a5", "30")],
           "plans": [_rec("a1", "100"), _rec("a6", "40")]})
    pr = _p(b, {"action": "process_run", "run_id": run_id})
    assert pr["status"] == "ok"
    assert pr["result"]["block_report"]["status"] == "success"
    # a5 actual-only and a6 plan-only become missing_record exceptions.
    missing = [e for e in pr["result"]["exceptions"] if e["exception_type"] == "missing_record"]
    assert len(missing) == 2


# -- resolve_exception -----------------------------------------------------------

def test_resolve_exception_transitions_and_rejects_bad_status():
    b = FinanceReconciliationWorkflowBlock()
    r = _mk_run(b)
    run_id = r["result"]["run"]["id"]
    _p(b, {"action": "set_run_data", "run_id": run_id, "actuals": [_rec("a1", "200")], "plans": []})
    pr = _p(b, {"action": "process_run", "run_id": run_id})
    exc_id = pr["result"]["exceptions"][0]["id"]
    bad = _p(b, {"action": "resolve_exception", "exception_id": exc_id, "status": "fixed"})
    assert bad["status"] == "error"
    assert "Invalid resolution status" in bad["error"]
    ok = _p(b, {"action": "resolve_exception", "exception_id": exc_id, "status": "resolved"})
    assert ok["status"] == "ok"
    assert ok["result"]["exception"]["status"] == "resolved"


def test_unknown_actions_and_missing_runs():
    b = FinanceReconciliationWorkflowBlock()
    assert _p(b, {"action": "nope"})["status"] == "error"
    assert _p(b, {"action": "process_run", "run_id": "run-404"})["status"] == "error"
    assert _p(b, {"action": "list_exceptions", "run_id": "run-404", "tenant_id": "t1"})["status"] == "error"
