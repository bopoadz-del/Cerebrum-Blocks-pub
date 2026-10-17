"""Domain Pack integration tests — finance_ops, insurance_ops, retail_ops, investment_analysis.

Each pack loads through the real loader; one formula executes per pack;
one rule or decision table refuses per pack; production mode refuses
candidate packs by name. Implementation/oracle functions referenced by
the packs' `implementation`/`verification_oracle` fields live here.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.reasoning_kernel import ReasoningStatus
from app.reasoning_kernel.formulas import DeterministicFormulaExecutor, FormulaRegistry
from app.reasoning_kernel.loader import DomainPackLoader
from app.reasoning_kernel.rules import DecisionTableEngine, RuleEngine

PACKS = Path(__file__).resolve().parents[2] / "domain_packs"


# -- pack-referenced implementations + oracles -----------------------------


def _variance_impl(i):
    difference = abs(i["actual"] - i["plan"])
    if i["tolerance_amount"]:
        bound = i["tolerance_amount"]
    elif i["tolerance_percent"]:
        bound = i["plan"] * i["tolerance_percent"] / Decimal("100")
    else:
        bound = Decimal("0.01")
    return difference > bound


def _variance_oracle(**inputs):
    return _variance_impl(inputs)


def _commission_impl(i):
    return i["premium"] * i["rate"]


def _commission_oracle(**inputs):
    return _commission_impl(inputs)


def _sharpe_impl(i):
    return (i["mean_return"] - i["risk_free"]) / i["stddev"]


def _sharpe_oracle(**inputs):
    return _sharpe_impl(inputs)


def _altman_impl(i):
    return (
        Decimal("1.2") * i["x1"]
        + Decimal("1.4") * i["x2"]
        + Decimal("3.3") * i["x3"]
        + Decimal("0.6") * i["x4"]
        + Decimal("1.0") * i["x5"]
    )


def _altman_oracle(**inputs):
    return _altman_impl(inputs)


def _load(domain_id):
    return DomainPackLoader().load_path(str(PACKS / domain_id / "pack.json"))


def _registry(pack):
    impls = {
        "fin.variance_exceeds_tolerance": _variance_impl,
        "ins.commission_amount": _commission_impl,
        "inv.sharpe_ratio": _sharpe_impl,
        "inv.altman_z": _altman_impl,
    }
    reg = FormulaRegistry()
    for formula in pack.formulas:
        reg.register(formula, impls[formula.formula_id])
    return reg


# -- finance_ops -----------------------------------------------------------


def test_finance_pack_loads_and_variance_formula_runs():
    pack = _load("finance_ops")
    out = DeterministicFormulaExecutor(_registry(pack)).execute(
        "fin.variance_exceeds_tolerance",
        {
            "actual": "100.50",
            "plan": "100.00",
            "tolerance_amount": "0",
            "tolerance_percent": "0",
        },
        currency="SAR",
    )
    assert out.status is ReasoningStatus.SUCCESS
    assert out.formulas_applied[0]["output"] == "True"


def test_finance_pack_action_allowlist_refuses():
    pack = _load("finance_ops")
    out = RuleEngine(pack.rules).evaluate({"action_type_known": False})
    assert out.status is ReasoningStatus.VALIDATION_ERROR
    assert out.rules_applied[0]["rule_id"] == "fin.action_type_allowlist"


def test_finance_pack_production_mode_refuses_candidate():
    pack = _load("finance_ops")
    out = DeterministicFormulaExecutor(_registry(pack), production=True).execute(
        "fin.variance_exceeds_tolerance",
        {"actual": "100.50", "plan": "100.00", "tolerance_amount": "0", "tolerance_percent": "0"},
        currency="SAR",
    )
    assert out.status is ReasoningStatus.PERMISSION_DENIED


# -- insurance_ops ---------------------------------------------------------


def test_insurance_pack_commission_formula_and_rate_table():
    pack = _load("insurance_ops")
    table = DecisionTableEngine(pack.decision_tables[0])
    rate = table.evaluate({"level": "standard"}).recommended_actions[0]["outcome"]["rate"]
    out = DeterministicFormulaExecutor(_registry(pack)).execute(
        "ins.commission_amount", {"premium": "10000", "rate": rate}, currency="HKD"
    )
    assert out.status is ReasoningStatus.SUCCESS
    assert out.formulas_applied[0]["output"] == "7500.0000"
    unknown = table.evaluate({"level": "intern"})
    assert unknown.recommended_actions[0]["outcome"]["refuse"] == "unknown_level"


def test_insurance_pack_boolean_money_rule_refuses():
    pack = _load("insurance_ops")
    out = RuleEngine(pack.rules).evaluate({"bool_money_input": True})
    assert out.status is ReasoningStatus.VALIDATION_ERROR
    assert out.rules_applied[0]["rule_id"] == "ins.boolean_is_not_money"


# -- retail_ops ------------------------------------------------------------


def test_retail_pack_unpermitted_action_refuses():
    pack = _load("retail_ops")
    out = RuleEngine(pack.rules).evaluate({"action_permitted": False})
    assert out.status is ReasoningStatus.VALIDATION_ERROR
    assert out.rules_applied[0]["rule_id"] == "ret.unpermitted_action_is_refused"


def test_retail_pack_mixed_embedder_refuses():
    pack = _load("retail_ops")
    out = RuleEngine(pack.rules).evaluate({"embedder_mismatch": True})
    assert out.status is ReasoningStatus.VALIDATION_ERROR


# -- investment_analysis ---------------------------------------------------


def test_investment_pack_sharpe_and_altman():
    pack = _load("investment_analysis")
    executor = DeterministicFormulaExecutor(_registry(pack))
    sharpe = executor.execute("inv.sharpe_ratio", {"mean_return": "0.10", "stddev": "0.20", "risk_free": "0.045"})
    assert sharpe.formulas_applied[0]["output"] == "0.2750"
    altman = executor.execute(
        "inv.altman_z", {"x1": "0.1", "x2": "0.2", "x3": "0.3", "x4": "0.4", "x5": "0.5"}
    )
    assert altman.formulas_applied[0]["output"] == "2.1300"


def test_investment_pack_zero_variance_refuses():
    pack = _load("investment_analysis")
    out = DeterministicFormulaExecutor(_registry(pack)).execute(
        "inv.sharpe_ratio", {"mean_return": "0.10", "stddev": "0", "risk_free": "0.045"}
    )
    assert out.status is ReasoningStatus.VALIDATION_ERROR
    assert "precondition failed" in out.explanation
