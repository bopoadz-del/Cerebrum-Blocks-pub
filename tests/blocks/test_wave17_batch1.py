"""Wave 1.7 batch-1 regression tests.

Locks the survey's cluster fixes: finance_v2 honest cash-flow/return
parsing, aviation airport-code extraction (no prose-word false
positives), FHIR camelCase payload validation, and the multi-currency
commission engine resolution.
"""

from app.blocks.agency_commission_engine import AgencyCommissionEngineBlock
from app.blocks.aviation_v2 import AviationBlockV2
from app.blocks.finance_v2 import FinanceBlockV2
from app.core.connector_events import Observation, Patient


def test_finance_cash_flow_series_parsed_from_rows():
    block = FinanceBlockV2()
    text = "Year 1: 1,000\nYear 2: 2,000\nY3 -500k"
    assert block._extract_cash_flows(text) == [1000.0, 2000.0, -500000.0]


def test_finance_returns_series_and_empty_on_garbage():
    block = FinanceBlockV2()
    assert block._extract_returns("Year 1: 12.5%\nYear 2: 8%") == [12.5, 8.0]
    assert block._extract_cash_flows("No numbers here, just prose.") == []
    assert block._extract_returns("") == []


def test_aviation_airports_are_uppercase_codes_not_prose():
    block = AviationBlockV2()
    found = block._extract_airports(
        "Crew briefing at JFK airport. THE form must be filed before departure."
    )
    values = {e["value"] for e in found}
    assert "JFK" in values
    assert "THE" not in values
    assert "FORM" not in values


def test_fhir_camelcase_payloads_validate():
    patient = Patient.model_validate(
        {
            "resourceType": "Patient",
            "id": "pat-1",
            "name": [{"family": "Doe", "given": ["Jane"]}],
            "birthDate": "1990-01-01",
            "gender": "female",
        }
    )
    assert patient.birth_date == "1990-01-01"

    obs = Observation.model_validate(
        {
            "resourceType": "Observation",
            "id": "obs-1",
            "status": "final",
            "code": {"text": "Heart rate"},
            "effectiveDateTime": "2026-09-17T10:00:00Z",
            "valueQuantity": {"value": 72, "unit": "beats/min"},
        }
    )
    assert obs.effective_date_time == "2026-09-17T10:00:00Z"


def test_commission_currency_resolution_order():
    block = AgencyCommissionEngineBlock()
    assert block._currency({"currency": "eur"}) == "EUR"
    assert block._currency({"policy": {"currency": "gbp"}}) == "GBP"
    # Request-level currency wins over the policy-level one.
    assert (
        block._currency({"currency": "usd", "policy": {"currency": "gbp"}})
        == "USD"
    )
    assert block._currency({}) == "USD"  # schedule default
