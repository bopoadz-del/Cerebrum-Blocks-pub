"""Review purchase verification is backed by the billing block's ledger.

Fail-closed: an unwired billing dependency or a ledger without a purchase
record refuses verification — the pair can never be minted verified=True
out of thin air. Uses the real BillingBlock (in-memory ledger, no Stripe).
"""

from __future__ import annotations

import asyncio

from app.blocks.billing import BillingBlock
from app.blocks.review import ReviewBlock


def _run(block, action: str, **data):
    return asyncio.run(block.process(dict(data), params={"action": action}))


def _review_with_billing() -> ReviewBlock:
    review = ReviewBlock()
    billing = BillingBlock()
    review.wire("billing", billing)
    return review, billing


def test_verify_refuses_without_purchase_record():
    review, _billing = _review_with_billing()
    out = _run(review, "verify_purchase", user_id="u1", block_id="pdf")
    assert out["verified"] is False
    assert "no purchase record" in out["error"]


def test_verify_refuses_when_billing_not_wired():
    review = ReviewBlock()
    out = _run(review, "verify_purchase", user_id="u1", block_id="pdf")
    assert out["verified"] is False
    assert "not wired" in out["error"]


def test_verify_succeeds_after_purchase_recorded():
    review, billing = _review_with_billing()
    recorded = _run(billing, "record_purchase", api_key="u1", block_id="pdf")
    assert recorded["recorded"] is True
    out = _run(review, "verify_purchase", user_id="u1", block_id="pdf")
    assert out["verified"] is True


def test_purchase_ledger_is_scoped_per_block():
    review, billing = _review_with_billing()
    _run(billing, "record_purchase", api_key="u1", block_id="pdf")
    other = _run(review, "verify_purchase", user_id="u1", block_id="webhook")
    assert other["verified"] is False
    assert "no purchase record" in other["error"]


def test_submit_review_requires_verified_pair():
    review, billing = _review_with_billing()
    refused = _run(
        review,
        "submit_review",
        block_id="pdf",
        user_id="u1",
        rating=5,
        review_text="great",
    )
    assert "error" in refused
    assert "Verified purchase required" in refused["error"]

    _run(billing, "record_purchase", api_key="u1", block_id="pdf")
    _run(review, "verify_purchase", user_id="u1", block_id="pdf")
    accepted = _run(
        review,
        "submit_review",
        block_id="pdf",
        user_id="u1",
        rating=5,
        review_text="great",
    )
    assert "error" not in accepted
    assert accepted["submitted"] is True
    assert accepted["verified"] is True


def test_billing_check_purchase_requires_ids():
    billing = BillingBlock()
    out = _run(billing, "check_purchase", api_key="only-key")
    assert out["purchased"] is False
    assert "block_id required" in out["error"]
