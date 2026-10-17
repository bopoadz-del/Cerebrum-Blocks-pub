"""guest_rfm_segmentation: donor-ladder parity + refusal paths.

Donor: <private-repo>-v2 guest_intelligence/segmentation.py rfm_score().
"""
from __future__ import annotations

import asyncio

import pytest

from app.blocks.guest_rfm_segmentation import (
    GuestRfmSegmentationBlock,
    RfmScorer,
    rfm_score,
)


def _run(coro):
    return asyncio.run(coro)


def test_donor_ladder_champions():
    # Donor parity: recency<=30 -> r=3, frequency>=5 -> f=3, monetary>=5000 -> m=3
    assert rfm_score(10, 6, 9000) == {
        "r": 3, "f": 3, "m": 3, "score": 9, "segment": "champions", "advisory": True,
    }


def test_donor_ladder_at_risk():
    # recency>90 -> r=1, frequency<2 -> f=1, monetary<1500 -> m=1
    assert rfm_score(120, 0, 100) == {
        "r": 1, "f": 1, "m": 1, "score": 3, "segment": "at_risk", "advisory": True,
    }


def test_donor_ladder_loyal_boundary():
    # total 6 -> loyal (recency<=30 r=3, frequency 2 f=2, monetary 0 m=1)
    res = rfm_score(20, 2, 0)
    assert res["segment"] == "loyal" and res["score"] == 6


def test_donor_ladder_promising_boundary():
    # total 4 -> promising (r=2, f=1, m=1)
    res = rfm_score(50, 0, 500)
    assert res["segment"] == "promising" and res["score"] == 4


def test_threshold_boundaries():
    # r=3 iff <=30, r=2 iff <=90
    assert rfm_score(30, 0, 0)["r"] == 3
    assert rfm_score(30.1, 0, 0)["r"] == 2
    assert rfm_score(90, 0, 0)["r"] == 2
    assert rfm_score(90.1, 0, 0)["r"] == 1
    # f=3 iff >=5, f=2 iff >=2
    assert rfm_score(999, 5, 0)["f"] == 3
    assert rfm_score(999, 4, 0)["f"] == 2
    assert rfm_score(999, 1, 0)["f"] == 1
    # m=3 iff >=5000, m=2 iff >=1500
    assert rfm_score(999, 0, 5000)["m"] == 3
    assert rfm_score(999, 0, 4999)["m"] == 2
    assert rfm_score(999, 0, 1499)["m"] == 1


def test_rfm_scorer_custom_thresholds():
    scorer = RfmScorer(r_thresholds=(7.0, 14.0), f_thresholds=(10, 3), m_thresholds=(1000.0, 500.0))
    res = scorer.score(5, 12, 2000)
    assert res["r"] == 3 and res["f"] == 3 and res["m"] == 3
    assert res["segment"] == "champions"


def test_block_score_uses_config_thresholds():
    b = GuestRfmSegmentationBlock(config={"r_thresholds": [7.0, 14.0], "f_thresholds": [10, 3], "m_thresholds": [1000.0, 500.0]})
    r = _run(b.execute({"action": "score", "recency_days": 5, "frequency": 12, "monetary": 2000}))
    assert r["status"] == "ok"
    assert r["result"]["segment"] == "champions"
    assert r["result"]["r"] == 3 and r["result"]["f"] == 3 and r["result"]["m"] == 3


def test_block_score_advisory_always():
    b = GuestRfmSegmentationBlock()
    r = _run(b.execute({"action": "score", "recency_days": 1000, "frequency": 0, "monetary": 0}))
    assert r["status"] == "ok"
    assert r["result"]["advisory"] is True
    assert r["result"]["segment"] == "at_risk"


def test_refused_missing_monetary():
    b = GuestRfmSegmentationBlock()
    r = _run(b.execute({"action": "score", "recency_days": 5, "frequency": 2}))
    assert r["status"] == "refused"
    assert "monetary" in r["error"]


def test_refused_non_numeric_recency():
    b = GuestRfmSegmentationBlock()
    r = _run(b.execute({"action": "score", "recency_days": "last-week", "frequency": 2, "monetary": 100}))
    assert r["status"] == "refused"
    assert "recency_days" in r["error"]


def test_refused_bool_frequency():
    b = GuestRfmSegmentationBlock()
    r = _run(b.execute({"action": "score", "recency_days": 5, "frequency": True, "monetary": 100}))
    assert r["status"] == "refused"


def test_batch_scores_every_guest_and_refuses_bad_row():
    b = GuestRfmSegmentationBlock()
    ok = _run(b.execute({"action": "batch", "guests": [
        {"guest_id": "g1", "recency_days": 3, "frequency": 9, "monetary": 12000},
        {"guest_id": "g2", "recency_days": 400, "frequency": 0, "monetary": 0},
    ]}))
    assert ok["status"] == "ok"
    assert [row["segment"] for row in ok["result"]["segments"]] == ["champions", "at_risk"]
    assert ok["result"]["segments"][0]["guest_id"] == "g1"
    refused = _run(b.execute({"action": "batch", "guests": [
        {"guest_id": "g1", "recency_days": 3, "frequency": 9, "monetary": 12000},
        {"guest_id": "g2", "recency_days": "x", "frequency": 0, "monetary": 0},
    ]}))
    assert refused["status"] == "refused"
    assert refused["detail"]["index"] == 1


def test_batch_requires_list():
    b = GuestRfmSegmentationBlock()
    r = _run(b.execute({"action": "batch", "guests": {"g1": 1}}))
    assert r["status"] == "refused"


def test_unknown_action_error():
    b = GuestRfmSegmentationBlock()
    r = _run(b.execute({"action": "predict"}))
    assert r["status"] == "error"
    assert "unknown action" in r["error"]


def test_non_dict_input_does_not_crash():
    b = GuestRfmSegmentationBlock()
    r = _run(b.execute("hello"))
    assert r["status"] == "refused"


@pytest.mark.asyncio
async def test_process_is_async_coroutine():
    b = GuestRfmSegmentationBlock()
    r = await b.process({"action": "score", "recency_days": 1, "frequency": 9, "monetary": 99999})
    assert r["status"] == "ok"
    assert r["result"]["segment"] == "champions"
