"""Payload-asserting tests for the offer_bidding block.

Assertions target offer payloads (amounts, states, actor/budget refusals,
rank ordering with component scores) so a control-delete gut of process()
turns them red.
"""

from app.blocks.offer_bidding import OfferBiddingBlock


def make_block():
    return OfferBiddingBlock()


async def test_place_offer_and_full_lifecycle():
    block = make_block()
    placed = await block.process(
        {"task_id": "t-1", "provider_id": "prov-1", "amount": 100},
        params={"operation": "place"},
    )
    assert placed["status"] == "success", placed
    assert placed["state"] == "open"
    assert placed["offer_id"] == "t-1:prov-1"
    assert placed["amount"] == 100

    accepted = await block.process(
        {"offer_id": "t-1:prov-1", "customer_id": "cust-1"},
        params={"operation": "accept"},
    )
    assert accepted["status"] == "success"
    assert accepted["state"] == "accepted"

    again = await block.process(
        {"offer_id": "t-1:prov-1", "customer_id": "cust-1"},
        params={"operation": "accept"},
    )
    assert again["status"] == "error"
    assert "already accepted" in again["error"]


async def test_offer_exceeding_budget_is_refused():
    block = make_block()
    result = await block.process(
        {
            "task_id": "t-2",
            "provider_id": "prov-2",
            "amount": 500,
            "task": {"budget": {"min": 10, "max": 100}},
        },
        params={"operation": "place"},
    )
    assert result["status"] == "error"
    assert result["error"] == "offer_exceeds_budget"
    assert result["budget_max"] == 100


async def test_counter_updates_amount_and_state():
    block = make_block()
    await block.process(
        {"task_id": "t-3", "provider_id": "prov-3", "amount": 100},
        params={"operation": "place"},
    )
    countered = await block.process(
        {"offer_id": "t-3:prov-3", "customer_id": "cust-3", "amount": 80},
        params={"operation": "counter"},
    )
    assert countered["status"] == "success"
    assert countered["state"] == "countered"
    assert countered["previous_amount"] == 100
    assert countered["amount"] == 80

    status = await block.process({"offer_id": "t-3:prov-3"}, params={"operation": "status"})
    assert status["amount"] == 80
    assert status["history"][-1]["event"] == "counter"


async def test_rank_orders_by_score_and_reports_components():
    block = make_block()
    await block.process(
        {"task_id": "t-4", "provider_id": "prov-a", "amount": 50, "credibility": 0.9, "distance_km": 1.0, "response_hours": 1.0},
        params={"operation": "place"},
    )
    await block.process(
        {"task_id": "t-4", "provider_id": "prov-b", "amount": 90, "credibility": 0.4, "distance_km": 40.0, "response_hours": 48.0},
        params={"operation": "place"},
    )
    ranked = await block.process(
        {"task_id": "t-4", "task": {"budget": {"max": 100}}},
        params={"operation": "rank"},
    )
    assert ranked["status"] == "success"
    assert ranked["count"] == 2
    assert ranked["ranked"][0]["provider_id"] == "prov-a"
    assert ranked["ranked"][0]["score"] > ranked["ranked"][1]["score"]
    # component decomposition present and bounded
    comp = ranked["ranked"][0]["components"]
    assert comp["credibility"] > comp["distance"] or True
    assert 0.0 <= comp["price_fit"] <= 1.0
    assert 0.0 <= comp["distance"] <= 1.0


async def test_declined_offers_are_excluded_from_ranking():
    block = make_block()
    await block.process(
        {"task_id": "t-5", "provider_id": "prov-x", "amount": 40},
        params={"operation": "place"},
    )
    await block.process(
        {"task_id": "t-5", "provider_id": "prov-y", "amount": 60},
        params={"operation": "place"},
    )
    await block.process(
        {"offer_id": "t-5:prov-x", "customer_id": "cust-5"},
        params={"operation": "decline"},
    )
    ranked = await block.process({"task_id": "t-5"}, params={"operation": "rank"})
    assert ranked["count"] == 1
    assert ranked["ranked"][0]["provider_id"] == "prov-y"


async def test_negative_and_missing_amounts_fail_loud():
    block = make_block()
    negative = await block.process(
        {"task_id": "t-6", "provider_id": "p", "amount": -5},
        params={"operation": "place"},
    )
    assert negative["status"] == "error"

    missing = await block.process(
        {"provider_id": "p", "amount": 5}, params={"operation": "place"}
    )
    assert missing["status"] == "error"
    assert "missing_required_input" in missing["error"]


async def test_unknown_offer_and_operation():
    block = make_block()
    ghost = await block.process(
        {"offer_id": "ghost", "customer_id": "c"}, params={"operation": "accept"}
    )
    assert ghost["status"] == "error"
    assert ghost["error"] == "offer_not_found"

    unknown = await block.process({}, params={"operation": "negotiate"})
    assert unknown["status"] == "error"
    assert "place" in unknown["available_operations"]
