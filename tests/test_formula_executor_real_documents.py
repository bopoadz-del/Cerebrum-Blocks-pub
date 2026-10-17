"""formula_executor must reproduce REAL documents' own numbers.

The fixture ``tests/fixtures/real_doc_formula_vectors.json`` (30 KB) is
harvested from The_Fork, where it backs
``tests/test_formulas_against_real_documents.py``. It holds vectors extracted
from an operator's actual project documents:

  * 247 line extensions from two real priced bills -- a contract-volume .xls
    and a scanned 2016-17 tender BOQ answer key. Rows were accepted only where
    the bill's own qty x rate = amount within 2%, so OCR noise cannot poison
    the vectors.
  * 19 activities from a real 2013 Primavera P6 baseline .xer where the
    scheduler's stored total float agrees with its stored dates (the other
    1,261 rows are multi-calendar artifacts, excluded at extraction).
  * an interim payment on the bill's own 15.18M validated-row valuation at the
    retention rate the real contract states (10%).

The_Fork's own test drives ``app.agents.formulas.run_formula`` over these
vectors. This repo has no ``app.agents`` package and no
``unit_cost_total`` / ``critical_path_float`` / ``calculate_interim_payment``
bindings, so that file could not be harvested as written (reported as a
finding). The vectors are driven through the block this repo DOES ship --
``FormulaExecutorBlock`` -- so the real artifact still gates real arithmetic
instead of sitting unused in tests/fixtures/.

Descriptions and identifiers are stripped from the fixture; the numbers are
the test.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.blocks.formula_executor import FormulaExecutorBlock

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "real_doc_formula_vectors.json"


@pytest.fixture(scope="module")
def vectors():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def block():
    return FormulaExecutorBlock()


async def _run(block, code, values, description):
    out = await block.process({
        "custom_code": code,
        "input_values": dict(values),
        "formula_description": description,
    })
    assert out["status"] == "success", out
    assert out["generated_code"] == code
    assert out["input_values"] == dict(values)
    return out["execution_result"]


def test_the_fixture_is_substantial(vectors):
    """A gutted fixture must fail loudly, not pass emptily."""
    assert len(vectors["line_extensions"]) >= 240
    assert len(vectors["xer_floats"]) >= 15
    assert vectors["payment"]["gross_valuation"] > 1_000_000


@pytest.mark.asyncio
async def test_every_real_bill_line_extension_reproduces_the_bill(block, vectors):
    """247 real rows: the block's sandbox must land qty x rate on the amount
    the bill records (2% tolerance -- the same arithmetic gate the bills
    themselves passed; most rows are exact)."""
    code = "result = quantity * unit_rate"
    failures = []
    for i, v in enumerate(vectors["line_extensions"]):
        total = await _run(
            block, code,
            {"quantity": v["qty"], "unit_rate": v["rate"]},
            "BOQ line-item extension",
        )
        if abs(total - v["amount"]) > 0.02 * v["amount"]:
            failures.append(f"row {i} ({v['source']}): "
                            f"{v['qty']} x {v['rate']} = {total} != {v['amount']}")
    assert not failures, "\n".join(failures)


def test_most_real_extensions_are_exact_to_the_cent(vectors):
    """The 2% band is for the bills' own rounding; the arithmetic itself must
    be exact wherever the bill is exact -- and that is nearly every row."""
    exact = sum(
        1 for v in vectors["line_extensions"]
        if abs(v["qty"] * v["rate"] - v["amount"]) < 0.01
    )
    assert exact / len(vectors["line_extensions"]) > 0.9


@pytest.mark.asyncio
async def test_cpm_float_reproduces_the_real_p6_scheduler(block, vectors):
    """19 real baseline activities: total float computed from P6's own dates
    must match P6's stored total float within a day, and criticality must
    agree. TF = LS - ES; negative float is critical, not merely late."""
    code = "result = late_start - early_start"
    failures = []
    for v in vectors["xer_floats"]:
        tf = await _run(
            block, code,
            {"early_start": v["es"], "early_finish": v["ef"],
             "late_start": v["ls"], "late_finish": v["lf"]},
            "total float from scheduler dates",
        )
        if abs(tf - v["p6_total_float_days"]) > 1.0:
            failures.append(f"TF {tf} vs P6 {v['p6_total_float_days']}")
            continue
        is_critical = tf < 1e-9
        if v["p6_total_float_days"] <= 0 and not is_critical:
            failures.append(f"P6 critical, computed float {tf}")
        if v["p6_total_float_days"] > 1.5 and is_critical:
            failures.append(f"P6 float {v['p6_total_float_days']}, computed critical")
    assert not failures, "\n".join(failures)


@pytest.mark.asyncio
async def test_lf_minus_ef_agrees_with_ls_minus_es_on_the_real_baseline(block, vectors):
    """The scheduler's own consistency check: on these 19 rows LF - EF must
    give the same total float as LS - ES."""
    failures = []
    for v in vectors["xer_floats"]:
        by_start = await _run(
            block, "result = late_start - early_start",
            {"early_start": v["es"], "late_start": v["ls"]},
            "total float from start dates",
        )
        by_finish = await _run(
            block, "result = late_finish - early_finish",
            {"early_finish": v["ef"], "late_finish": v["lf"]},
            "total float from finish dates",
        )
        if abs(by_start - by_finish) > 1e-6:
            failures.append(f"LS-ES {by_start} != LF-EF {by_finish}")
    assert not failures, "\n".join(failures)


@pytest.mark.asyncio
async def test_interim_payment_on_the_real_valuation_at_the_contract_retention(
    block, vectors,
):
    """Gross = the contract bill's validated-row total; retention 10% as the
    real conditions of contract state."""
    p = vectors["payment"]
    values = {"gross_valuation": p["gross_valuation"],
              "retention_percent": p["retention_percent"]}
    retention = await _run(
        block, "result = gross_valuation * retention_percent / 100.0",
        values, "interim payment retention",
    )
    net = await _run(
        block, "result = gross_valuation - gross_valuation * retention_percent / 100.0",
        values, "interim payment net certified",
    )
    assert retention == pytest.approx(p["gross_valuation"] * 0.10, abs=0.01)
    assert net == pytest.approx(p["gross_valuation"] * 0.90, abs=0.01)
    assert retention + net == pytest.approx(p["gross_valuation"], abs=0.01)
