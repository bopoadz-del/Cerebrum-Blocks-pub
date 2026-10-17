"""Payload-asserting tests for the loyalty_referrals block.

Assertions target the credit ledger (two-sided grants, caps, expiry,
FIFO redemption, exact Decimal balances) so a control-delete gut of
process() turns them red.
"""

from app.blocks.loyalty_referrals import LoyaltyReferralsBlock


def make_block():
    return LoyaltyReferralsBlock()


async def test_referral_grants_both_sides():
    block = make_block()
    result = await block.process(
        {"referral_key": "r1", "referrer_id": "u1", "referee_id": "u2", "step": 0},
        params={"operation": "referral"},
    )
    assert result["status"] == "success"
    assert result["referrer_reward"] == "10.00"
    assert result["referee_reward"] == "5.00"
    assert result["referrer_uses"] == 1

    ref_balance = await block.process({"user_id": "u1", "step": 0}, params={"operation": "balance"})
    assert ref_balance["balance"] == "10.00"
    fee_balance = await block.process({"user_id": "u2", "step": 0}, params={"operation": "balance"})
    assert fee_balance["balance"] == "5.00"


async def test_duplicate_key_and_self_referral_refused():
    block = make_block()
    await block.process(
        {"referral_key": "r2", "referrer_id": "u3", "referee_id": "u4"},
        params={"operation": "referral"},
    )
    dup = await block.process(
        {"referral_key": "r2", "referrer_id": "u3", "referee_id": "u5"},
        params={"operation": "referral"},
    )
    assert dup["status"] == "error"
    assert dup["error"] == "referral_key_already_used"

    self_ref = await block.process(
        {"referral_key": "r3", "referrer_id": "u3", "referee_id": "u3"},
        params={"operation": "referral"},
    )
    assert self_ref["status"] == "error"
    assert self_ref["error"] == "self_referral_refused"


async def test_referral_cap_is_enforced():
    block = LoyaltyReferralsBlock(config={"max_referrals_per_user": 2})
    await block.process(
        {"referral_key": "r4", "referrer_id": "u6", "referee_id": "u7"},
        params={"operation": "referral"},
    )
    await block.process(
        {"referral_key": "r5", "referrer_id": "u6", "referee_id": "u8"},
        params={"operation": "referral"},
    )
    capped = await block.process(
        {"referral_key": "r6", "referrer_id": "u6", "referee_id": "u9"},
        params={"operation": "referral"},
    )
    assert capped["status"] == "error"
    assert capped["error"] == "referral_cap_reached"
    assert capped["cap"] == 2


async def test_redeem_fifo_and_insufficient_balance():
    block = make_block()
    # Two credits: 10 at step 0, 5 at step 10
    await block.process(
        {"referral_key": "r7", "referrer_id": "u10", "referee_id": "u11", "step": 0},
        params={"operation": "referral"},
    )
    await block.process(
        {"user_id": "u10", "amount": "5.00", "reason": "promo", "step": 10},
        params={"operation": "issue_credit"},
    )
    # Redeem 12 -> burns 10 first (older), then 2 of the newer 5
    redeemed = await block.process(
        {"user_id": "u10", "amount": "12.00", "step": 20},
        params={"operation": "redeem"},
    )
    assert redeemed["status"] == "success"
    assert redeemed["redeemed"] == "12.00"
    assert redeemed["applied"][0]["amount"] == "10.00"
    assert redeemed["applied"][1]["amount"] == "2.00"
    assert redeemed["balance_after"] == "3.00"

    over = await block.process(
        {"user_id": "u10", "amount": "4.00", "step": 20},
        params={"operation": "redeem"},
    )
    assert over["status"] == "error"
    assert over["error"] == "insufficient_balance"
    assert over["available"] == "3.00"


async def test_credits_expire_by_step():
    block = LoyaltyReferralsBlock(config={"default_expiry_steps": 100})
    await block.process(
        {"referral_key": "r8", "referrer_id": "u12", "referee_id": "u13", "step": 0},
        params={"operation": "referral"},
    )
    fresh = await block.process({"user_id": "u12", "step": 50}, params={"operation": "balance"})
    assert fresh["balance"] == "10.00"

    expired = await block.process({"user_id": "u12", "step": 150}, params={"operation": "balance"})
    assert expired["balance"] == "0.00"
    assert expired["credit_count"] == 0


async def test_missing_inputs_and_unknown_operation():
    block = make_block()
    missing = await block.process({"user_id": "u14"}, params={"operation": "redeem"})
    assert missing["status"] == "error"
    assert "missing_required_input" in missing["error"]

    negative = await block.process(
        {"user_id": "u14", "amount": "-5.00", "reason": "x"},
        params={"operation": "issue_credit"},
    )
    assert negative["status"] == "error"

    unknown = await block.process({}, params={"operation": "cash_out"})
    assert unknown["status"] == "error"
    assert "referral" in unknown["available_operations"]
