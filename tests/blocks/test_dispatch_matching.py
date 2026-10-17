"""Payload-asserting tests for the dispatch_matching block.

Assertions target matching payloads (candidate ranking, component scores,
capacity guards, exclusive assignment, timeout lifecycle) so a control-
delete gut of process() turns them red.
"""

from app.blocks.dispatch_matching import DispatchMatchingBlock


def make_block():
    return DispatchMatchingBlock()


async def _register(block):
    await block.process(
        {"worker_id": "w1", "skills": ["driving", "heavy"], "capacity": 2, "reputation": 0.9, "location": {"lat": 1, "lng": 1}},
        params={"operation": "register_worker"},
    )
    await block.process(
        {"worker_id": "w2", "skills": ["walking"], "capacity": 1, "reputation": 0.3, "location": {"lat": 1, "lng": 1}},
        params={"operation": "register_worker"},
    )
    await block.process(
        {"job_id": "j1", "required_skills": ["driving"], "distance_km": 2.0},
        params={"operation": "register_job"},
    )


async def test_match_ranks_by_skill_distance_load_reputation():
    block = make_block()
    await _register(block)
    result = await block.process({"job_id": "j1"}, params={"operation": "match"})
    assert result["status"] == "success"
    assert result["count"] == 2
    assert result["candidates"][0]["worker_id"] == "w1"
    assert result["candidates"][0]["score"] > result["candidates"][1]["score"]
    comp = result["candidates"][0]["components"]
    assert comp["skills"] == 1.0  # w1 has the required skill
    assert comp["distance"] > 0.9  # 2 km of 30 km max
    assert comp["load"] == 1.0  # no load yet
    assert comp["reputation"] == 0.9


async def test_assign_accept_and_reject_lifecycle():
    block = make_block()
    await _register(block)
    assigned = await block.process(
        {"job_id": "j1", "worker_id": "w1", "step": 10},
        params={"operation": "assign"},
    )
    assert assigned["status"] == "success"
    assert assigned["state"] == "assigned"

    accepted = await block.process(
        {"job_id": "j1", "worker_id": "w1", "step": 20},
        params={"operation": "accept"},
    )
    assert accepted["status"] == "success"
    assert accepted["state"] == "accepted"

    # Second job assignment respects capacity guard on load (capacity 2, load 1 -> ok)
    await block.process(
        {"job_id": "j2", "required_skills": ["driving"]},
        params={"operation": "register_job"},
    )
    ok = await block.process(
        {"job_id": "j2", "worker_id": "w1", "step": 5},
        params={"operation": "assign"},
    )
    assert ok["status"] == "success"


async def test_accept_timeout_reopens_job():
    block = make_block()
    await _register(block)
    await block.process(
        {"job_id": "j1", "worker_id": "w1", "step": 0},
        params={"operation": "assign"},
    )
    late = await block.process(
        {"job_id": "j1", "worker_id": "w1", "step": 99},  # > 50-step timeout
        params={"operation": "accept"},
    )
    assert late["status"] == "error"
    assert late["error"] == "accept_timeout_expired"
    assert late["state"] == "open"


async def test_wrong_worker_cannot_respond():
    block = make_block()
    await _register(block)
    await block.process(
        {"job_id": "j1", "worker_id": "w1", "step": 0},
        params={"operation": "assign"},
    )
    intruder = await block.process(
        {"job_id": "j1", "worker_id": "w2", "step": 1},
        params={"operation": "accept"},
    )
    assert intruder["status"] == "error"
    assert intruder["error"] == "job_assigned_to_other_worker"


async def test_capacity_saturation_is_refused():
    block = make_block()
    await block.process(
        {"worker_id": "w3", "skills": ["driving"], "capacity": 1, "reputation": 0.5},
        params={"operation": "register_worker"},
    )
    await block.process(
        {"job_id": "j3", "required_skills": ["driving"]},
        params={"operation": "register_job"},
    )
    await block.process(
        {"job_id": "j4", "required_skills": ["driving"]},
        params={"operation": "register_job"},
    )
    first = await block.process({"job_id": "j3", "worker_id": "w3"}, params={"operation": "assign"})
    assert first["status"] == "success"
    second = await block.process({"job_id": "j4", "worker_id": "w3"}, params={"operation": "assign"})
    assert second["status"] == "error"
    assert second["error"] == "worker_at_capacity"


async def test_inactive_worker_never_matches():
    block = make_block()
    await block.process(
        {"worker_id": "w4", "skills": ["driving"], "active": False},
        params={"operation": "register_worker"},
    )
    await block.process(
        {"job_id": "j5", "required_skills": ["driving"]},
        params={"operation": "register_job"},
    )
    result = await block.process({"job_id": "j5"}, params={"operation": "match"})
    assert result["count"] == 0


async def test_missing_ids_and_unknown_operation():
    block = make_block()
    ghost_job = await block.process({"job_id": "ghost"}, params={"operation": "match"})
    assert ghost_job["status"] == "error"
    assert ghost_job["error"] == "job_not_found"

    missing = await block.process({}, params={"operation": "assign"})
    assert missing["status"] == "error"
    assert "missing_required_input" in missing["error"]

    unknown = await block.process({}, params={"operation": "teleport"})
    assert unknown["status"] == "error"
    assert "match" in unknown["available_operations"]
