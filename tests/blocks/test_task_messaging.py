"""Payload-asserting tests for the task_messaging block.

Assertions target thread/message payloads (participant gates, sequences,
moderation flags, cursors, evidence digests) so a control-delete gut of
process() turns them red.
"""

from app.blocks.task_messaging import TaskMessagingBlock


def make_block():
    return TaskMessagingBlock()


async def test_thread_create_and_send_roundtrip():
    block = make_block()
    thread = await block.process(
        {"task_id": "t-1", "participants": ["cust-1", "prov-1"]},
        params={"operation": "thread"},
    )
    assert thread["status"] == "success"
    assert thread["thread_id"] == "thread:t-1"
    assert thread["participants"] == ["cust-1", "prov-1"]

    sent = await block.process(
        {"thread_id": "thread:t-1", "sender": "cust-1", "body": "When can you start?"},
        params={"operation": "send"},
    )
    assert sent["status"] == "success"
    assert sent["seq"] == 1
    assert sent["flagged"] is False

    reply = await block.process(
        {"thread_id": "thread:t-1", "sender": "prov-1", "body": "Tomorrow morning works."},
        params={"operation": "send"},
    )
    assert reply["seq"] == 2


async def test_non_participant_is_refused():
    block = make_block()
    await block.process(
        {"task_id": "t-2", "participants": ["cust-2", "prov-2"]},
        params={"operation": "thread"},
    )
    result = await block.process(
        {"thread_id": "thread:t-2", "sender": "intruder", "body": "hello"},
        params={"operation": "send"},
    )
    assert result["status"] == "error"
    assert result["error"] == "sender_not_participant"
    assert "prov-2" in result["participants"]


async def test_moderation_flags_and_strict_mode_refuses():
    block = make_block()
    await block.process(
        {"task_id": "t-3", "participants": ["cust-3", "prov-3"]},
        params={"operation": "thread"},
    )
    flagged = await block.process(
        {"thread_id": "thread:t-3", "sender": "cust-3", "body": "this is a scam"},
        params={"operation": "send"},
    )
    assert flagged["status"] == "success"
    assert flagged["flagged"] is True
    assert "scam" in flagged["flags"]

    strict = TaskMessagingBlock(config={"strict_moderation": True})
    await strict.process(
        {"task_id": "t-4", "participants": ["cust-4", "prov-4"]},
        params={"operation": "thread"},
    )
    refused = await strict.process(
        {"thread_id": "thread:t-4", "sender": "cust-4", "body": "total scam"},
        params={"operation": "send"},
    )
    assert refused["status"] == "error"
    assert refused["error"] == "message_refused_blocklist"


async def test_list_supports_after_cursor_and_limit():
    block = make_block()
    await block.process(
        {"task_id": "t-5", "participants": ["cust-5", "prov-5"]},
        params={"operation": "thread"},
    )
    for body in ["one", "two", "three"]:
        await block.process(
            {"thread_id": "thread:t-5", "sender": "cust-5", "body": body},
            params={"operation": "send"},
        )
    listed = await block.process({"thread_id": "thread:t-5"}, params={"operation": "list"})
    assert listed["count"] == 3
    assert listed["next_after"] == 3

    paged = await block.process(
        {"thread_id": "thread:t-5", "after": 1}, params={"operation": "list"}
    )
    assert paged["count"] == 2
    assert paged["messages"][0]["seq"] == 2

    limited = await block.process(
        {"thread_id": "thread:t-5", "limit": 2}, params={"operation": "list"}
    )
    assert limited["count"] == 2


async def test_evidence_bundle_is_deterministic():
    block = make_block()
    await block.process(
        {"task_id": "t-6", "participants": ["cust-6", "prov-6"]},
        params={"operation": "thread"},
    )
    await block.process(
        {"thread_id": "thread:t-6", "sender": "cust-6", "body": "evidence message"},
        params={"operation": "send"},
    )
    first = await block.process({"thread_id": "thread:t-6"}, params={"operation": "evidence"})
    second = await block.process({"thread_id": "thread:t-6"}, params={"operation": "evidence"})
    assert first["digest"] == second["digest"]
    assert first["message_count"] == 1
    assert len(first["digest"]) == 64


async def test_unknown_thread_and_empty_body_fail_loud():
    block = make_block()
    ghost = await block.process(
        {"thread_id": "ghost", "sender": "x", "body": "hi"},
        params={"operation": "send"},
    )
    assert ghost["status"] == "error"
    assert ghost["error"] == "thread_not_found"

    await block.process(
        {"task_id": "t-7", "participants": ["a", "b"]},
        params={"operation": "thread"},
    )
    empty = await block.process(
        {"thread_id": "thread:t-7", "sender": "a", "body": "   "},
        params={"operation": "send"},
    )
    assert empty["status"] == "error"
    assert empty["error"] == "missing_required_input: body"

    unknown = await block.process({}, params={"operation": "broadcast"})
    assert unknown["status"] == "error"
    assert "send" in unknown["available_operations"]
