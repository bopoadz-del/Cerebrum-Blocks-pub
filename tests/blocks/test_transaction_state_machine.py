"""Payload-asserting tests for the transaction_state_machine block.

These tests assert the machine's actual payloads (states, actor guards,
idempotent replays, error listings) rather than the envelope shape, so a
control-delete gut of ``process()`` turns them red.
"""

import pytest

from app.blocks.transaction_state_machine import (
    TransactionStateMachineBlock,
    TRANSITIONS,
)


def make_block():
    return TransactionStateMachineBlock()


async def test_task_happy_path_reaches_reviewed():
    block = make_block()
    steps = [
        ("post_offers", "provider", "offered"),
        ("accept_offer", "customer", "accepted"),
        ("start", "provider", "in_progress"),
        ("complete", "provider", "completed"),
        ("review", "customer", "reviewed"),
    ]
    for event, actor, expected in steps:
        result = await block.process(
            {"entity_id": "task-1", "vertical": "task", "event": event, "actor": actor}
        )
        assert result["status"] == "success", result
        assert result["to_state"] == expected, result
        assert result["from_state"] != expected
    # terminal state offers no events
    final = await block.process({"entity_id": "task-1", "vertical": "task"}, params={"operation": "allowed"})
    assert final["current_state"] == "reviewed"
    assert final["allowed_events"] == []


async def test_illegal_transition_reports_allowed_events():
    block = make_block()
    result = await block.process(
        {"entity_id": "task-2", "vertical": "task", "event": "review", "actor": "customer"}
    )
    assert result["status"] == "error"
    assert result["error"].startswith("invalid_transition")
    assert "post_offers" in result["allowed_events"]
    assert "cancel" in result["allowed_events"]


async def test_actor_not_permitted_is_refused():
    block = make_block()
    # Move the entity to offered first: actor checks apply to legal transitions.
    await block.process(
        {"entity_id": "task-3", "vertical": "task", "event": "post_offers", "actor": "provider"}
    )
    result = await block.process(
        {"entity_id": "task-3", "vertical": "task", "event": "accept_offer", "actor": "hacker"}
    )
    assert result["status"] == "error"
    assert result["error"].startswith("actor_not_permitted")
    assert result["allowed_actors"] == ["customer"]


async def test_transition_id_is_idempotent():
    block = make_block()
    payload = {
        "entity_id": "task-4",
        "vertical": "task",
        "event": "post_offers",
        "actor": "provider",
        "transition_id": "t-001",
    }
    first = await block.process(payload)
    second = await block.process(payload)
    assert first["status"] == "success"
    assert second["status"] == "success"
    assert second["idempotent"] is True
    # history must not grow on the replay
    assert second["history_length"] == first["history_length"] == 1


async def test_dispute_resolution_paths():
    block = make_block()
    for event, actor in [
        ("post_offers", "provider"),
        ("accept_offer", "customer"),
        ("start", "provider"),
        ("dispute", "customer"),
    ]:
        result = await block.process(
            {"entity_id": "task-5", "vertical": "task", "event": event, "actor": actor}
        )
        assert result["status"] == "success", result
    resolved = await block.process(
        {"entity_id": "task-5", "vertical": "task", "event": "resolve_refund", "actor": "platform"}
    )
    assert resolved["status"] == "success"
    assert resolved["to_state"] == "refunded"


async def test_missing_required_input_fails_loud():
    block = make_block()
    result = await block.process({"vertical": "task", "event": "start"})
    assert result["status"] == "error"
    assert "missing_required_input" in result["error"]


async def test_unknown_vertical_and_event():
    block = make_block()
    result = await block.process(
        {"entity_id": "x", "vertical": "spaceship", "event": "launch", "actor": "system"}
    )
    assert result["status"] == "error"
    assert "spaceship" in result["error"]


async def test_replay_validates_full_sequence():
    block = make_block()
    sequence = [
        {"event": "post_offers", "actor": "provider"},
        {"event": "accept_offer", "actor": "customer"},
        {"event": "start", "actor": "provider"},
        {"event": "complete", "actor": "provider"},
    ]
    result = await block.process(
        {"vertical": "task", "sequence": sequence}, params={"operation": "replay"}
    )
    assert result["status"] == "success"
    assert result["steps"] == 4
    assert result["failed"] is False
    assert result["final_state"] == "completed"

    bad = await block.process(
        {"vertical": "task", "sequence": [{"event": "review", "actor": "customer"}]},
        params={"operation": "replay"},
    )
    assert bad["failed"] is True


async def test_machine_describes_vertical():
    block = make_block()
    result = await block.process({}, params={"operation": "machine", "vertical": "trip"})
    assert result["status"] == "success"
    assert result["initial"] == "created"
    assert "match" in result["states"]["created"]
    assert "begin" in result["states"]["driver_en_route"]
