"""Finance reconciliation workflow â€” the run/exception state machine ported
from <private-repo> ``reconciliation/service.py``
(create_reconciliation_run, process_reconciliation_run, _variance_exceeds_
tolerance, _ensure_exception, resolve_exception, match rules).

The SQLAlchemy layer is not ported; the state machine is, exactly:
run_type must be in {actuals_vs_budget, actuals_vs_forecast, bank_vs_ledger,
intercompany}; bank_vs_ledger/intercompany fail the run with the donor's
honest message ("Run type ... not supported by honest reconciliation");
pending -> processing -> completed/failed with Decimal control totals;
per-scope tolerance rules; idempotent open-exception dedup (an identical
open exception is never created twice); and the actuals-vs-plan diff that
invokes the Store's finance_reconciliation block and merges its variances /
left_only / right_only into deduplicated ReconciliationException rows.

Actuals and plans are supplied by the caller (set_run_data or inline on
process_run) instead of the donor's tenant-scoped tables.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

DEFAULT_TOLERANCE = Decimal("0.01")

_VALID_RUN_TYPES = {
    "actuals_vs_budget",
    "actuals_vs_forecast",
    "bank_vs_ledger",
    "intercompany",
}


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "finance_reconciliation_workflow", "status": status, "result": result, "error": error, "detail": detail}


def _variance_exceeds_tolerance(
    difference: Decimal,
    tolerance_amount: Decimal | None,
    tolerance_percent: Decimal | None,
    plan_amount: Decimal,
) -> bool:
    """Return True if ``difference`` exceeds configured tolerances."""
    if tolerance_amount is not None and abs(difference) > tolerance_amount:
        return True
    if tolerance_percent is not None and plan_amount != Decimal("0"):
        percent_threshold = (abs(plan_amount) * tolerance_percent / Decimal("100")).quantize(
            Decimal("0.0001")
        )
        if abs(difference) > percent_threshold:
            return True
    if tolerance_amount is None and tolerance_percent is None and abs(difference) > DEFAULT_TOLERANCE:
        return True
    return False


_ReconciliationKey = tuple[str, str, str, str]


def _record_key(record: Dict[str, Any]) -> _ReconciliationKey:
    """The donor's grouping key: (account_id, legal_entity_id, period, currency_code)."""
    return (
        str(record.get("account_id") or ""),
        str(record.get("legal_entity_id") or ""),
        str(record.get("period") or ""),
        str(record.get("currency_code") or ""),
    )


def _group_records(records: List[Dict[str, Any]]) -> dict[_ReconciliationKey, Decimal]:
    grouped: dict[_ReconciliationKey, Decimal] = {}
    for record in records:
        key = _record_key(record)
        try:
            amount = Decimal(str(record.get("amount", "0")))
        except Exception:
            continue
        grouped[key] = grouped.get(key, Decimal("0")) + amount
    return grouped


class FinanceReconciliationWorkflowBlock(UniversalBlock):
    """Reconciliation run/exception state machine ported from <private-repo>."""

    name = "finance_reconciliation_workflow"
    version = "1.0.0"
    description = (
        "real: reconciliation run/exception state machine ported from "
        "<private-repo> backend/app/reconciliation/service.py. "
        "pending->processing->completed/failed ReconciliationRun lifecycle "
        "across run_type in {actuals_vs_budget, actuals_vs_forecast, "
        "bank_vs_ledger, intercompany}; bank_vs_ledger/intercompany fail the "
        "run honestly (not supported); per-scope tolerance rules; Decimal "
        "control totals; idempotent open-exception dedup; block-level "
        "variances merged from the Store finance_reconciliation block. "
        "In-process store; actuals/plans supplied by the caller."
    )
    layer = 3
    tags = ["finance", "reconciliation", "workflow", "state-machine", "exceptions", "finance_ops"]
    requires = ["finance_reconciliation"]

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "create_run", "tenant_id": "t1", "run_type": "actuals_vs_budget", "source_period": "2026-01"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._runs: Dict[str, Dict[str, Any]] = {}
        self._rules: Dict[str, Dict[str, Any]] = {}
        self._exceptions: List[Dict[str, Any]] = []
        self._run_data: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "create_run")).lower()
        try:
            if action == "create_run":
                return self._create_run(payload)
            if action == "get_run":
                return self._get_run(payload)
            if action == "list_runs":
                return self._list_runs(payload)
            if action == "create_match_rule":
                return self._create_match_rule(payload)
            if action == "list_match_rules":
                return self._list_match_rules(payload)
            if action == "set_run_data":
                return self._set_run_data(payload)
            if action == "process_run":
                return await self._process_run(payload)
            if action == "list_exceptions":
                return self._list_exceptions(payload)
            if action == "resolve_exception":
                return self._resolve_exception(payload)
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["create_run", "get_run", "list_runs", "create_match_rule", "list_match_rules", "set_run_data", "process_run", "list_exceptions", "resolve_exception"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)

    # -- run lifecycle -----------------------------------------------------

    def _create_run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tenant_id = str(payload.get("tenant_id", ""))
        if not tenant_id:
            return _envelope("error", error="tenant_id is required")
        run_type = str(payload.get("run_type", ""))
        if run_type not in _VALID_RUN_TYPES:
            return _envelope("error", error="Invalid run_type", detail={"run_type": run_type, "valid": sorted(_VALID_RUN_TYPES)})
        source_period = str(payload.get("source_period", ""))
        if not source_period:
            return _envelope("error", error="source_period is required")
        run_id = f"run-{len(self._runs) + 1}"
        # The donor enqueues a background job for the run; the job reference is
        # recorded in-process (no worker is ported).
        job_id = f"job-{len(self._runs) + 1}"
        self._runs[run_id] = {
            "id": run_id,
            "tenant_id": tenant_id,
            "project_id": payload.get("project_id"),
            "run_type": run_type,
            "source_period": source_period,
            "status": "pending",
            "source_actuals_total": None,
            "source_plan_total": None,
            "variance_amount": None,
            "variance_percent": None,
            "job_id": job_id,
            "created_by": str(payload.get("created_by", "")),
        }
        return _envelope("ok", {"run": self._runs[run_id]})

    def _get_run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        run = self._runs.get(str(payload.get("run_id", "")))
        if run is None or str(payload.get("tenant_id", "")) not in ("", str(run.get("tenant_id", ""))):
            return _envelope("error", error="Reconciliation run not found", detail={"run_id": payload.get("run_id")})
        return _envelope("ok", {"run": run})

    def _list_runs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        rows = [r for r in self._runs.values() if str(payload.get("tenant_id", "")) in ("", str(r.get("tenant_id", "")))]
        return _envelope("ok", {"runs": rows, "count": len(rows)})

    def _set_run_data(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        run_id = str(payload.get("run_id", ""))
        if run_id not in self._runs:
            return _envelope("error", error="Reconciliation run not found", detail={"run_id": run_id})
        actuals = payload.get("actuals")
        plans = payload.get("plans")
        if not isinstance(actuals, list) or not isinstance(plans, list):
            return _envelope("error", error="actuals and plans must both be record lists")
        self._run_data[run_id] = {"actuals": actuals, "plans": plans}
        return _envelope("ok", {"run_id": run_id, "actual_records": len(actuals), "plan_records": len(plans)})

    # -- match rules -------------------------------------------------------

    def _create_match_rule(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        tenant_id = str(payload.get("tenant_id", ""))
        if not tenant_id:
            return _envelope("error", error="tenant_id is required")
        name = str(payload.get("name", ""))
        if not name:
            return _envelope("error", error="name is required")
        rule_id = f"rule-{len(self._rules) + 1}"
        tolerance_amount = payload.get("tolerance_amount")
        tolerance_percent = payload.get("tolerance_percent")
        try:
            if tolerance_amount is not None:
                tolerance_amount = Decimal(str(tolerance_amount))
            if tolerance_percent is not None:
                tolerance_percent = Decimal(str(tolerance_percent))
        except Exception:
            return _envelope("error", error="tolerance_amount/tolerance_percent must be decimal numbers")
        self._rules[rule_id] = {
            "id": rule_id,
            "tenant_id": tenant_id,
            "project_id": payload.get("project_id"),
            "name": name,
            "source_system_a": str(payload.get("source_system_a", "")),
            "source_system_b": str(payload.get("source_system_b", "")),
            "match_keys": payload.get("match_keys") if isinstance(payload.get("match_keys"), dict) else {},
            "tolerance_amount": tolerance_amount,
            "tolerance_percent": tolerance_percent,
            "is_active": bool(payload.get("is_active", True)),
        }
        return _envelope("ok", {"rule": self._rules[rule_id]})

    def _list_match_rules(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        rows = [r for r in self._rules.values() if str(payload.get("tenant_id", "")) in ("", str(r.get("tenant_id", "")))]
        return _envelope("ok", {"rules": rows, "count": len(rows)})

    # -- exceptions --------------------------------------------------------

    def _ensure_exception(
        self,
        run: Dict[str, Any],
        account_id: str | None,
        exception_type: str,
        severity: str,
        expected: Decimal | None,
        actual: Decimal | None,
        difference: Decimal | None,
        description: str,
    ) -> None:
        """Create an exception unless an identical open one already exists for this run."""
        for exc in self._exceptions:
            if (
                exc["reconciliation_run_id"] == run["id"]
                and exc["account_id"] == account_id
                and exc["exception_type"] == exception_type
                and exc["status"] == "open"
            ):
                return
        self._exceptions.append(
            {
                "id": f"exc-{len(self._exceptions) + 1}",
                "reconciliation_run_id": run["id"],
                "exception_type": exception_type,
                "severity": severity,
                "account_id": account_id,
                "expected_amount": str(expected) if expected is not None else None,
                "actual_amount": str(actual) if actual is not None else None,
                "difference": str(difference) if difference is not None else None,
                "description": description,
                "status": "open",
            }
        )

    def _list_exceptions(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        run_id = str(payload.get("run_id", ""))
        run = self._runs.get(run_id)
        if run is None or str(payload.get("tenant_id", "")) not in ("", str(run.get("tenant_id", ""))):
            return _envelope("error", error="Reconciliation run not found", detail={"run_id": run_id})
        rows = [e for e in self._exceptions if e["reconciliation_run_id"] == run_id]
        return _envelope("ok", {"exceptions": rows, "count": len(rows)})

    def _resolve_exception(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        exc_id = str(payload.get("exception_id", ""))
        exc = next((e for e in self._exceptions if e["id"] == exc_id), None)
        if exc is None:
            return _envelope("error", error="Exception not found", detail={"exception_id": exc_id})
        new_status = str(payload.get("status", ""))
        if new_status not in {"resolved", "ignored"}:
            return _envelope("error", error="Invalid resolution status", detail={"status": new_status, "valid": ["resolved", "ignored"]})
        exc["status"] = new_status
        if payload.get("description"):
            exc["description"] = str(payload.get("description"))
        return _envelope("ok", {"exception": exc})

    # -- processing --------------------------------------------------------

    async def _process_run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        run_id = str(payload.get("run_id", ""))
        run = self._runs.get(run_id)
        if run is None:
            return _envelope("error", error="Reconciliation run not found", detail={"run_id": run_id})
        if run["status"] not in {"pending", "processing"}:
            return _envelope("refused", error=f"Cannot process run in status {run['status']}", detail={"run_id": run_id, "status": run["status"]})

        run["status"] = "processing"

        if run["run_type"] not in {"actuals_vs_budget", "actuals_vs_forecast"}:
            # Other run types are not yet supported by this honest comparison path.
            run["status"] = "failed"
            return _envelope(
                "refused",
                error=f"Run type {run['run_type']} not supported by honest reconciliation",
                detail={"run_id": run_id, "status": "failed"},
            )

        data = self._run_data.get(run_id, {})
        actuals = payload.get("actuals", data.get("actuals", []))
        plans = payload.get("plans", data.get("plans", []))
        if not isinstance(actuals, list) or not isinstance(plans, list):
            run["status"] = "failed"
            return _envelope("refused", error="no actuals/plans loaded for run (use set_run_data or pass them on process_run)", detail={"run_id": run_id})

        plan_name = "budget" if run["run_type"] == "actuals_vs_budget" else "forecast"
        grouped_actuals = _group_records(actuals)
        grouped_plans = _group_records(plans)

        # Compute control totals using exact Decimal arithmetic.
        actuals_total = sum(grouped_actuals.values(), Decimal("0"))
        plans_total = sum(grouped_plans.values(), Decimal("0"))
        variance_amount = actuals_total - plans_total
        variance_percent = (
            Decimal("0")
            if plans_total == Decimal("0")
            else (variance_amount / plans_total * Decimal("100")).quantize(Decimal("0.0001"))
        )

        run["source_actuals_total"] = str(actuals_total)
        run["source_plan_total"] = str(plans_total)
        run["variance_amount"] = str(variance_amount)
        run["variance_percent"] = str(variance_percent)

        # Load active rule tolerances for the run scope.
        rules = [r for r in self._rules.values() if str(r.get("tenant_id", "")) == str(run.get("tenant_id", ""))]
        active_rule = next((r for r in rules if r.get("is_active")), None)
        tolerance_amount = active_rule.get("tolerance_amount") if active_rule else None
        tolerance_percent = active_rule.get("tolerance_percent") if active_rule else None

        # Compare per-account actuals against the plan (budget or forecast).
        all_keys = set(grouped_actuals) | set(grouped_plans)
        for key in all_keys:
            account_id = key[0]
            actual_amount = grouped_actuals.get(key, Decimal("0"))
            plan_amount = grouped_plans.get(key, Decimal("0"))
            difference = actual_amount - plan_amount

            if account_id is None:
                continue

            if key not in grouped_plans:
                self._ensure_exception(
                    run,
                    account_id=account_id,
                    exception_type="missing_record",
                    severity="error",
                    expected=None,
                    actual=actual_amount,
                    difference=difference,
                    description=f"Actual exists but no matching {plan_name} record",
                )
            elif key not in grouped_actuals:
                self._ensure_exception(
                    run,
                    account_id=account_id,
                    exception_type="missing_record",
                    severity="error",
                    expected=plan_amount,
                    actual=None,
                    difference=difference,
                    description=f"{plan_name.title()} exists but no matching actual record",
                )
            elif _variance_exceeds_tolerance(difference, tolerance_amount, tolerance_percent, plan_amount):
                self._ensure_exception(
                    run,
                    account_id=account_id,
                    exception_type="amount_mismatch",
                    severity="error",
                    expected=plan_amount,
                    actual=actual_amount,
                    difference=difference,
                    description="Actual amount exceeds configured tolerance",
                )

        # Invoke the Store finance_reconciliation block and merge its
        # variances / left_only / right_only into deduplicated exceptions.
        report = await self._invoke_reconciliation_block(run, grouped_actuals, grouped_plans)
        run["status"] = "completed"
        exceptions = [e for e in self._exceptions if e["reconciliation_run_id"] == run_id]
        open_count = sum(1 for e in exceptions if e["status"] == "open")
        return _envelope(
            "ok",
            {
                "run": run,
                "block_report": report,
                "exceptions": exceptions,
                "open_exception_count": open_count,
            },
        )

    async def _invoke_reconciliation_block(
        self,
        run: Dict[str, Any],
        actuals: dict[_ReconciliationKey, Decimal],
        plans: dict[_ReconciliationKey, Decimal],
    ) -> Dict[str, Any]:
        """Invoke the Store finance_reconciliation block and return its report."""
        left_records = [
            {"account_id": key[0], "legal_entity_id": key[1] or None, "period": key[2], "currency": key[3], "amount": str(amount)}
            for key, amount in actuals.items()
        ]
        right_records = [
            {"account_id": key[0], "legal_entity_id": key[1] or None, "period": key[2], "currency": key[3], "amount": str(amount)}
            for key, amount in plans.items()
        ]

        tolerance = DEFAULT_TOLERANCE
        rules = [r for r in self._rules.values() if str(r.get("tenant_id", "")) == str(run.get("tenant_id", ""))]
        active_rule = next((r for r in rules if r.get("is_active")), None)
        if active_rule and active_rule.get("tolerance_amount") is not None:
            tolerance = active_rule["tolerance_amount"]

        from app.blocks.finance_reconciliation import FinanceReconciliationBlock

        invoker = FinanceReconciliationBlock()
        try:
            report = await invoker.process({
                "left_records": left_records,
                "right_records": right_records,
                "group_by": ["account_id", "legal_entity_id", "period", "currency"],
                "amount_field": "amount",
                "tolerance": str(tolerance),
            })
        except Exception as exc:  # noqa: BLE001
            # Block invocation is advisory; do not fail the run because of it.
            return {"status": "block_error", "error": str(exc), "error_kind": error_kind(exc)}

        # Merge block-level variances into exceptions.
        if report.get("status") == "success":
            for variance in report.get("variances", []):
                key = variance.get("key", {})
                account_id = key.get("account_id")
                expected = Decimal(variance.get("right_amount", "0"))
                actual = Decimal(variance.get("left_amount", "0"))
                diff = Decimal(variance.get("variance", "0"))
                self._ensure_exception(
                    run,
                    account_id=account_id,
                    exception_type="amount_mismatch",
                    severity="error",
                    expected=expected,
                    actual=actual,
                    difference=diff,
                    description="Variance flagged by finance_reconciliation block",
                )
            for left_only in report.get("left_only", []):
                key = left_only.get("key", {})
                account_id = key.get("account_id")
                actual = Decimal(left_only.get("left_amount", "0"))
                diff = Decimal(left_only.get("variance", "0"))
                self._ensure_exception(
                    run,
                    account_id=account_id,
                    exception_type="missing_record",
                    severity="error",
                    expected=None,
                    actual=actual,
                    difference=diff,
                    description="Record present in actuals but missing from plan",
                )
            for right_only in report.get("right_only", []):
                key = right_only.get("key", {})
                account_id = key.get("account_id")
                expected = Decimal(right_only.get("right_amount", "0"))
                diff = Decimal(right_only.get("variance", "0"))
                self._ensure_exception(
                    run,
                    account_id=account_id,
                    exception_type="missing_record",
                    severity="error",
                    expected=expected,
                    actual=None,
                    difference=diff,
                    description="Record present in plan but missing from actuals",
                )

        return report
