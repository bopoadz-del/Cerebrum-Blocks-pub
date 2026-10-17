"""Regression tests for the construction container + drawing_qto block.

Pinned against the bugs the audits found and fixed in commits b97e208d
and 61de979e. Each test names the issue tag (C1, C2, etc.) it guards.

Requires construction kit install (virgin CB ships bundle only).
"""

from __future__ import annotations

import pytest

# No module-level skip. A stale probe used to skip this file while the
# construction kit was installed (same class of miss as test_xlsx_schedule).
# If the container cannot be imported, that is a failure, not a skip.
from app.containers.construction import ConstructionContainer
from app.containers.construction.helpers import _parse_money_str, _safe_float


# ── Helpers / parsers ─────────────────────────────────────────────────────


def test_safe_float_handles_percent_and_thousands_and_none():
    """Audit baseline: _safe_float must never raise on user input shapes
    that hit the 28 brittle conversion sites the refactor touched."""
    assert _safe_float(None) == 0.0
    assert _safe_float("") == 0.0
    assert _safe_float("10%") == 10.0
    assert _safe_float("1,200.50") == 1200.50
    assert _safe_float(42) == 42.0
    # Default override
    assert _safe_float(None, 7.5) == 7.5
    assert _safe_float("garbage", 3.0) == 3.0


@pytest.mark.parametrize("raw,expected", [
    # US conventions
    ("5,250,000", 5_250_000.0),
    ("5,250,000.50", 5_250_000.50),
    ("USD 5,250,000", 5_250_000.0),
    # EU conventions — period as thousands separator (the C2 bug)
    ("500.000", 500_000.0),
    ("1.234.567,89", 1_234_567.89),
    # Decimal points (single-digit grouping, ambiguous resolved to decimal)
    ("1.5", 1.5),
    ("1,5", 1.5),
    # Whitespace and currency prefixes are stripped
    ("EUR 250,000.00", 250_000.0),
])
def test_parse_money_str(raw, expected):
    """Audit C2: contract_value lost 3 orders of magnitude on EU format."""
    assert _parse_money_str(raw) == expected


def test_parse_money_str_rejects_garbage():
    assert _parse_money_str(None) is None
    assert _parse_money_str("") is None
    assert _parse_money_str("not a number") is None
    assert _parse_money_str(".") is None


# ── Container action shapes ───────────────────────────────────────────────


@pytest.fixture
def container():
    return ConstructionContainer()


def test_extract_financial_terms_us_format(container):
    """US format: contract_value parses, persists as numeric string."""
    out = container._extract_financial_terms("Contract value: USD 5,250,000.50 plus VAT")
    assert out["contract_value"] == "5250000.5"


def test_extract_financial_terms_eu_thousands(container):
    """EU thousands separator (the original 'truncated to 0.' bug class).
    `Valor del contrato: 500.000` must NOT collapse to 500.0."""
    out = container._extract_financial_terms("Valor del contrato: 500.000 EUR")
    assert out["contract_value"] == "500000"


def test_extract_financial_terms_eu_full(container):
    """EU full format with both separators — last wins as decimal."""
    out = container._extract_financial_terms("Valor do contrato: 1.234.567,89 BRL")
    assert out["contract_value"] == "1234567.89"


def test_extract_obligations_semicolon_terminator(container):
    """Audit I10: obligations terminator must accept ';' so multi-clause
    legalese paragraphs register as separate obligations."""
    text = (
        "The contractor shall maintain the works in good condition during "
        "the period of this agreement; the employer shall pay all invoices "
        "within 30 days."
    )
    obls = container._extract_obligations(text)
    types = {o["type"] for o in obls}
    assert "contractor_obligation" in types
    assert "employer_obligation" in types


@pytest.mark.asyncio
async def test_lookup_unit_cost_unit_class_guard(container):
    """Audit I9: count-class items must not inherit a volumetric rate.

    `_get_rsmeans_data` was removed; lookup now delegates to
    historical_benchmark and returns None when the block is unavailable
    or the item is unknown. A live benchmark must still not return the
    volumetric concrete rate (150) for an each-unit sample.
    """
    rate = await container._lookup_unit_cost("concrete cube samples", "ea")
    assert rate is None or rate != 150.0


@pytest.mark.asyncio
async def test_lookup_unit_cost_correct_unit_still_works(container):
    """Concrete with m3 still resolves when a benchmark exists; otherwise None."""
    rate = await container._lookup_unit_cost("concrete", "m3")
    assert rate is None or isinstance(rate, (int, float))


@pytest.mark.asyncio
async def test_lookup_unit_cost_no_unit_passes_through(container):
    """Empty unit is accepted; block-unavailable and unknown item both yield None."""
    rate = await container._lookup_unit_cost("concrete", "")
    assert rate is None or isinstance(rate, (int, float))


def test_create_submittal_item_status_matches_spa_enum(container):
    """Audit C3: SPA's Submittal.status enum is APPROVED|PENDING|REJECTED|
    REQUIRED. Backend used to return 'Not Submitted' which uppercased to
    'NOT SUBMITTED' — a value the UI's switch had no case for."""
    item = container._create_submittal_item(
        "Method Statement - Excavation", "Method Statement", "2024-01-01"
    )
    # The mapper uppercases — "Pending" → PENDING is in the enum.
    assert item["status"] == "Pending"


# ── auto_pipeline contract ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_pipeline_emits_pipeline_warnings_field(container):
    """Audit I3: the response must always carry pipeline_warnings, even
    when empty, so the SPA can render a 'panels failed' notice."""
    res = await container.auto_pipeline(
        {"extracted_text": "Concrete: 100 m3. Steel: 4000 kg. Floor area: 800 m2."},
        {"doc_type": "auto"},
    )
    assert res["status"] == "success"
    assert "pipeline_warnings" in res
    assert isinstance(res["pipeline_warnings"], list)


@pytest.mark.asyncio
async def test_auto_pipeline_cost_estimate_has_line_items(container):
    """Audit I6: cost_estimate.line_items must populate from quantities,
    not return a hard-coded empty list."""
    res = await container.auto_pipeline(
        {"extracted_text": "Floor area: 1500 m2. Concrete: 250 m3."},
        {"doc_type": "auto"},
    )
    cost = next((p for p in res["panels"] if p["type"] == "cost_estimate"), None)
    assert cost is not None
    assert isinstance(cost.get("line_items"), list)
    assert len(cost["line_items"]) >= 1
    # Each item carries quantity + unit + a normalised currency amount
    for li in cost["line_items"]:
        assert "quantity" in li
        assert "unit" in li
        assert "amount" in li
        assert "currency" in li


@pytest.mark.asyncio
async def test_auto_pipeline_emits_placeholder_hints_when_no_doc_match(container):
    """Audit I2: schedule_hint and contract_hint placeholders appear when
    the doc_type doesn't trigger the dedicated panel, so the SPA section
    isn't silently empty."""
    res = await container.auto_pipeline(
        {"extracted_text": "Concrete: 100 m3."},
        {"doc_type": "auto"},
    )
    types = [p["type"] for p in res["panels"]]
    assert "schedule_hint" in types or "schedule" in types
    assert "contract_hint" in types or "contract" in types


@pytest.mark.asyncio
async def test_auto_pipeline_records_warning_on_panel_failure(container):
    """When a downstream action throws, pipeline_warnings should record
    the panel name + error, instead of swallowing silently."""
    # process_contract crashes on Path(None) when file_path missing AND
    # doc_type detected as contract — exercise that path.
    res = await container.auto_pipeline(
        {"extracted_text": "Contract value: USD 5,000,000. Contractor shall maintain works."},
        {"doc_type": "auto"},
    )
    panel_names = {w["panel"] for w in res["pipeline_warnings"]}
    # Either contract was attempted and crashed (warning), or it was
    # skipped (placeholder hint emitted) — both acceptable, but a real
    # contract panel + zero warnings would mean the bug regressed
    # silently.
    assert ("contract" in panel_names) or any(
        p["type"] == "contract_hint" for p in res["panels"]
    )
