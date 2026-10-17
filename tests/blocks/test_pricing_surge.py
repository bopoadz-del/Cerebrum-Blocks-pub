"""Payload-asserting tests for the pricing_surge block.

Assertions target the fare math (Decimal totals, surge tiers, caps,
decomposed breakdowns) so a control-delete gut of process() turns them
red.
"""

from app.blocks.pricing_surge import PricingSurgeBlock


def make_block():
    return PricingSurgeBlock()


async def test_quote_without_surge_exact_math():
    block = make_block()
    result = await block.process(
        {"distance_km": 10.0, "duration_min": 20.0, "demand_supply_ratio": 0.5},
        params={"operation": "quote"},
    )
    assert result["status"] == "success"
    b = result["breakdown"]
    assert b["base_fare"] == "2.50"
    assert b["distance_fee"] == "11.00"  # 10 km * 1.10
    assert b["time_fee"] == "5.00"  # 20 min * 0.25
    assert b["subtotal"] == "18.50"
    assert b["multiplier"] == "1.00"
    assert b["surge_amount"] == "0.00"
    assert result["total"] == "18.50"


async def test_surge_tiers_step_up_with_ratio():
    block = make_block()
    low = await block.process({"demand_supply_ratio": 1.0}, params={"operation": "surge"})
    assert low["multiplier"] == "1.00"
    assert low["surging"] is False

    mid = await block.process({"demand_supply_ratio": 1.5}, params={"operation": "surge"})
    assert mid["multiplier"] == "1.25"

    high = await block.process({"demand_supply_ratio": 2.5}, params={"operation": "surge"})
    assert high["multiplier"] == "1.50"

    extreme = await block.process({"demand_supply_ratio": 5.0}, params={"operation": "surge"})
    assert extreme["multiplier"] == "2.00"


async def test_surge_cap_is_enforced():
    block = PricingSurgeBlock(config={"max_multiplier": "1.50"})
    result = await block.process({"demand_supply_ratio": 9.0}, params={"operation": "surge"})
    assert result["multiplier"] == "1.50"


async def test_surged_quote_total_matches_breakdown():
    block = make_block()
    result = await block.process(
        {"distance_km": 10.0, "duration_min": 20.0, "demand_supply_ratio": 2.5},
        params={"operation": "quote"},
    )
    b = result["breakdown"]
    assert b["subtotal"] == "18.50"
    assert b["multiplier"] == "1.50"
    assert b["surge_amount"] == "9.25"  # 18.50 * 0.50
    assert result["total"] == "27.75"


async def test_tiers_operation_reports_config():
    block = make_block()
    result = await block.process({}, params={"operation": "tiers"})
    assert result["status"] == "success"
    assert result["base_fare"] == "2.50"
    assert result["max_multiplier"] == "3.00"
    assert any(t["floor"] == 1.2 for t in result["surge_tiers"])


async def test_negative_inputs_and_missing_fields_refused():
    block = make_block()
    negative = await block.process(
        {"distance_km": -1.0, "duration_min": 5.0}, params={"operation": "quote"}
    )
    assert negative["status"] == "error"

    missing = await block.process({"distance_km": 5.0}, params={"operation": "quote"})
    assert missing["status"] == "error"
    assert "missing_required_input" in missing["error"]

    bad_ratio = await block.process(
        {"demand_supply_ratio": -2.0}, params={"operation": "surge"}
    )
    assert bad_ratio["status"] == "error"

    unknown = await block.process({}, params={"operation": "bargain"})
    assert unknown["status"] == "error"
    assert "quote" in unknown["available_operations"]
