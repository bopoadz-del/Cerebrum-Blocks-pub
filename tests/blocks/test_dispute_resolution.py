"""Payload-asserting tests for the dispute_resolution block.

Assertions target the dispute payloads (state lifecycle, party gates,
platform-only resolution, evidence dedupe, escalation windows, history)
so a control-delete gut of process() turns them red.
"""

from app.blocks.dispute_resolution import DisputeResolutionBlock


def make_block():
    return DisputeResolutionBlock()


async def _open(block, dispute_id="d1", step=0):
    return await block.process(
        {
            "dispute_id": dispute_id,
            "task_id": "t-1",
            "claimant": "cust-1",
            "claim_type": "incomplete_work",
            "parties": ["cust-1", "prov-1"],
            "step": step,
        },
        params={"operation": "open"},
    )


async def test_full_lifecycle_to_resolution():
    block = make_block()
    opened = await _open(block)
    assert opened["status"] == "success"
    assert opened["state"] == "open"

    evidence = await block.process(
        {"dispute_id": "d1", "party": "cust-1", "digest": "abc123", "step": 5},
        params={"operation": "add_evidence"},
    )
    assert evidence["evidence_count"] == 1

    escalated = await block.process(
        {"dispute_id": "d1", "step": 150}, params={"operation": "escalate"}
    )
    assert escalated["state"] == "under_review"

    resolved = await block.process(
        {"dispute_id": "d1", "platform": "platform", "resolution": "refunded", "reason": "evidence supports claimant"},
        params={"operation": "resolve"},
    )
    assert resolved["status"] == "success"
    assert resolved["state"] == "resolved"
    assert resolved["resolution"] == "refunded"

    status = await block.process({"dispute_id": "d1"}, params={"operation": "status"})
    assert status["history"][-1]["event"] == "resolve"


async def test_only_platform_can_resolve():
    block = make_block()
    await _open(block)
    result = await block.process(
        {"dispute_id": "d1", "platform": "prov-1", "resolution": "refunded", "reason": "nope"},
        params={"operation": "resolve"},
    )
    assert result["status"] == "error"
    assert result["error"] == "resolver_not_platform"


async def test_resolution_requires_reason_and_valid_value():
    block = make_block()
    await _open(block)
    no_reason = await block.process(
        {"dispute_id": "d1", "platform": "platform", "resolution": "refunded", "reason": " "},
        params={"operation": "resolve"},
    )
    assert no_reason["status"] == "error"

    bad_value = await block.process(
        {"dispute_id": "d1", "platform": "platform", "resolution": "vaporize", "reason": "x"},
        params={"operation": "resolve"},
    )
    assert bad_value["status"] == "error"
    assert "refunded" in bad_value["error"]


async def test_evidence_dedupe_and_party_gate():
    block = make_block()
    await _open(block)
    first = await block.process(
        {"dispute_id": "d1", "party": "cust-1", "digest": "dup-digest"},
        params={"operation": "add_evidence"},
    )
    assert first["evidence_count"] == 1
    dup = await block.process(
        {"dispute_id": "d1", "party": "prov-1", "digest": "dup-digest"},
        params={"operation": "add_evidence"},
    )
    assert dup["status"] == "error"
    assert dup["error"] == "evidence_already_submitted"

    outsider = await block.process(
        {"dispute_id": "d1", "party": "outsider", "digest": "new-digest"},
        params={"operation": "add_evidence"},
    )
    assert outsider["status"] == "error"
    assert outsider["error"] == "party_not_in_dispute"


async def test_escalate_too_early_is_refused():
    block = make_block()
    await _open(block, step=0)
    early = await block.process(
        {"dispute_id": "d1", "step": 10}, params={"operation": "escalate"}
    )
    assert early["status"] == "error"
    assert early["error"] == "escalate_too_early"
    assert early["window_steps"] == 100


async def test_claimant_must_be_a_party():
    block = make_block()
    result = await block.process(
        {
            "dispute_id": "d2",
            "task_id": "t-2",
            "claimant": "outsider",
            "claim_type": "damage",
            "parties": ["cust-2", "prov-2"],
        },
        params={"operation": "open"},
    )
    assert result["status"] == "error"
    assert result["error"] == "claimant_not_a_party"


async def test_unknown_dispute_and_operation():
    block = make_block()
    ghost = await block.process({"dispute_id": "ghost"}, params={"operation": "status"})
    assert ghost["status"] == "error"
    assert ghost["error"] == "dispute_not_found"

    unknown = await block.process({}, params={"operation": "arbitrate"})
    assert unknown["status"] == "error"
    assert "open" in unknown["available_operations"]
