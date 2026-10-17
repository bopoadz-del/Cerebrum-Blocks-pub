"""Payload-asserting tests for the payment_escrow block.

Assertions target the actual escrow payloads (Decimal money math, state
transitions, error codes) so a control-delete gut of ``process()`` turns
them red.
"""

from decimal import Decimal

from app.blocks.payment_escrow import PaymentEscrowBlock


def make_block():
    return PaymentEscrowBlock()


async def test_hold_freezes_fee_at_hold_time():
    block = make_block()
    result = await block.process(
        {"payment_id": "p-1", "amount": "100.00", "platform_fee_rate": "0.15"},
        params={"operation": "hold"},
    )
    assert result["status"] == "success", result
    assert result["state"] == "held"
    assert result["amount"] == "100.00"
    assert result["platform_fee"] == "15.00"
    assert result["provider_net"] == "85.00"


async def test_fee_quote_matches_decimal_expectations():
    block = make_block()
    result = await block.process(
        {"amount": "33.33", "platform_fee_rate": "0.10", "platform_fee_fixed": "1.00"},
        params={"operation": "fee_quote"},
    )
    assert result["status"] == "success"
    # 33.33 * 0.10 = 3.333 -> 3.33 + 1.00 = 4.33 ; net = 29.00
    assert result["platform_fee"] == "4.33"
    assert result["provider_net"] == "29.00"


async def test_release_pays_net_and_second_release_is_refused():
    block = make_block()
    await block.process(
        {"payment_id": "p-2", "amount": "100.00"}, params={"operation": "hold"}
    )
    release = await block.process({"payment_id": "p-2"}, params={"operation": "release"})
    assert release["status"] == "success"
    assert release["state"] == "released"
    assert release["provider_net"] == "85.00"
    assert release["platform_fee"] == "15.00"

    again = await block.process({"payment_id": "p-2"}, params={"operation": "release"})
    assert again["status"] == "error"
    assert again["error"].startswith("invalid_transition")


async def test_partial_release_scales_fee_by_ratio():
    block = make_block()
    await block.process(
        {"payment_id": "p-3", "amount": "100.00", "platform_fee_rate": "0.15"},
        params={"operation": "hold"},
    )
    partial = await block.process(
        {"payment_id": "p-3", "amount": "40.00"}, params={"operation": "partial_release"}
    )
    assert partial["status"] == "success"
    # ratio 0.4 -> fee 6.00, net 34.00
    assert partial["platform_fee"] == "6.00"
    assert partial["provider_net"] == "34.00"
    assert partial["state"] == "partial"
    assert partial["remaining"] == "60.00"


async def test_partial_release_exceeding_held_is_refused():
    block = make_block()
    await block.process(
        {"payment_id": "p-4", "amount": "50.00"}, params={"operation": "hold"}
    )
    result = await block.process(
        {"payment_id": "p-4", "amount": "50.01"}, params={"operation": "partial_release"}
    )
    assert result["status"] == "error"
    assert result["error"] == "amount_exceeds_held"
    assert result["releasable"] == "50.00"


async def test_freeze_blocks_release_until_unfrozen():
    block = make_block()
    await block.process({"payment_id": "p-5", "amount": "100.00"}, params={"operation": "hold"})
    frozen = await block.process({"payment_id": "p-5"}, params={"operation": "freeze"})
    assert frozen["state"] == "frozen"

    blocked = await block.process({"payment_id": "p-5"}, params={"operation": "release"})
    assert blocked["status"] == "error"
    assert "frozen" in blocked["error"]

    unfrozen = await block.process({"payment_id": "p-5"}, params={"operation": "unfreeze"})
    assert unfrozen["state"] == "held"
    released = await block.process({"payment_id": "p-5"}, params={"operation": "release"})
    assert released["status"] == "success"
    assert released["state"] == "released"


async def test_refund_returns_unreleased_funds_only():
    block = make_block()
    await block.process({"payment_id": "p-6", "amount": "100.00"}, params={"operation": "hold"})
    refund = await block.process({"payment_id": "p-6"}, params={"operation": "refund"})
    assert refund["status"] == "success"
    assert refund["state"] == "refunded"
    assert refund["refunded_amount"] == "100.00"


async def test_refund_after_full_release_is_refused():
    block = make_block()
    await block.process({"payment_id": "p-7", "amount": "100.00"}, params={"operation": "hold"})
    await block.process({"payment_id": "p-7"}, params={"operation": "release"})
    result = await block.process({"payment_id": "p-7"}, params={"operation": "refund"})
    assert result["status"] == "error"
    assert result["error"].startswith("invalid_transition")


async def test_duplicate_hold_with_different_amount_is_refused():
    block = make_block()
    await block.process({"payment_id": "p-8", "amount": "100.00"}, params={"operation": "hold"})
    result = await block.process({"payment_id": "p-8", "amount": "120.00"}, params={"operation": "hold"})
    assert result["status"] == "error"
    assert result["error"] == "duplicate_hold_mismatch"


async def test_missing_required_input_and_unknown_operation():
    block = make_block()
    missing = await block.process({}, params={"operation": "release"})
    assert missing["status"] == "error"
    assert "missing_required_input" in missing["error"]

    unknown = await block.process({"payment_id": "p-9"}, params={"operation": "vaporize"})
    assert unknown["status"] == "error"
    assert "hold" in unknown["available_operations"]


async def test_status_snapshot_reports_remaining():
    block = make_block()
    await block.process(
        {"payment_id": "p-10", "amount": "100.00"}, params={"operation": "hold"}
    )
    await block.process(
        {"payment_id": "p-10", "amount": "25.00"}, params={"operation": "partial_release"}
    )
    status = await block.process({"payment_id": "p-10"}, params={"operation": "status"})
    assert status["state"] == "partial"
    assert status["released"] == "25.00"
    assert status["remaining"] == "75.00"
