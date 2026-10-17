"""Payload-asserting tests for the review_reputation block.

Assertions target the reputation math (decayed weighted averages, Laplace
confidence, fraud flags and effective weights) so a control-delete gut of
process() turns them red.
"""

from app.blocks.review_reputation import ReviewReputationBlock, decay_weight


def make_block():
    return ReviewReputationBlock()


async def test_decay_weight_halves_per_half_life():
    assert abs(decay_weight(0, 180) - 1.0) < 1e-9
    assert abs(decay_weight(180, 180) - 0.5) < 1e-9
    assert abs(decay_weight(360, 180) - 0.25) < 1e-9


async def test_score_smoothes_fresh_reviews():
    block = make_block()
    await block.process(
        {"reviewer": "c1", "reviewee": "p1", "task_id": "t1", "rating": 5, "age_days": 0},
        params={"operation": "submit"},
    )
    score = await block.process({"reviewee": "p1"}, params={"operation": "score"})
    assert score["status"] == "success"
    # Prior (weight 2 at 3.0) pulls the score below 5: (2*3 + 1*5) / 3 = 3.667
    assert 3.5 < score["score"] < 4.0
    assert score["review_count"] == 1
    assert 0.0 < score["confidence"] < 1.0


async def test_old_reviews_decay_toward_prior():
    block = make_block()
    await block.process(
        {"reviewer": "c2", "reviewee": "p2", "task_id": "t2", "rating": 5, "age_days": 1000},
        params={"operation": "submit"},
    )
    score = await block.process({"reviewee": "p2"}, params={"operation": "score"})
    # A 1000-day-old 5-star review decays to near-zero weight; score ~ neutral
    assert abs(score["score"] - 3.0) < 0.2


async def test_duplicate_review_and_self_review_refused():
    block = make_block()
    payload = {"reviewer": "c3", "reviewee": "p3", "task_id": "t3", "rating": 4}
    first = await block.process(payload, params={"operation": "submit"})
    assert first["status"] == "success"
    dup = await block.process(payload, params={"operation": "submit"})
    assert dup["status"] == "error"
    assert dup["error"] == "duplicate_review_refused"

    self_review = await block.process(
        {"reviewer": "p3", "reviewee": "p3", "task_id": "t3", "rating": 5},
        params={"operation": "submit"},
    )
    assert self_review["status"] == "error"
    assert self_review["error"] == "self_review_refused"


async def test_rating_out_of_range_refused():
    block = make_block()
    result = await block.process(
        {"reviewer": "c4", "reviewee": "p4", "task_id": "t4", "rating": 6},
        params={"operation": "submit"},
    )
    assert result["status"] == "error"
    assert "rating" in result["error"]


async def test_fraud_weight_flags_duplicates_and_reduces_weight():
    block = make_block()
    for i in range(2):
        await block.process(
            {"reviewer": "c5", "reviewee": "p5", "task_id": "t5", "rating": 5, "comment": "amazing work"},
            params={"operation": "submit"},
        )
    # different reviewer, same verbatim comment -> duplicate_comment flag
    await block.process(
        {"reviewer": "c6", "reviewee": "p5", "task_id": "t6", "rating": 5, "comment": "amazing work"},
        params={"operation": "submit"},
    )
    verdict = await block.process({"reviewee": "p5"}, params={"operation": "fraud_weight"})
    assert verdict["status"] == "success"
    assert "duplicate_comment" in verdict["flags"]
    assert verdict["effective_weight"] < 1.0


async def test_aggregate_scores_multiple_reviewees():
    block = make_block()
    await block.process(
        {"reviewer": "c7", "reviewee": "p7", "task_id": "t7", "rating": 4},
        params={"operation": "submit"},
    )
    await block.process(
        {"reviewer": "c8", "reviewee": "p8", "task_id": "t8", "rating": 2},
        params={"operation": "submit"},
    )
    result = await block.process(
        {"reviewees": ["p7", "p8"]}, params={"operation": "aggregate"}
    )
    assert result["status"] == "success"
    assert result["count"] == 2
    assert result["scores"][0]["score"] > result["scores"][1]["score"]


async def test_missing_required_input_and_unknown_operation():
    block = make_block()
    missing = await block.process({"reviewee": "p9"}, params={"operation": "submit"})
    assert missing["status"] == "error"
    assert "missing_required_input" in missing["error"]

    unknown = await block.process({}, params={"operation": "teleport"})
    assert unknown["status"] == "error"
    assert "submit" in unknown["available_operations"]
