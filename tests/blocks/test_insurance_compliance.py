"""Payload-asserting tests for the insurance_compliance block.

Assertions target coverage verdicts (required lines, expiry gaps, incident
verdicts) so a control-delete gut of process() turns them red.
"""

from app.blocks.insurance_compliance import InsuranceComplianceBlock


def make_block():
    return InsuranceComplianceBlock()


async def _register_active(block, provider_id="p1", line="public_liability"):
    await block.process(
        {
            "provider_id": provider_id,
            "policy_id": f"pol-{provider_id}-{line}",
            "line": line,
            "valid_from": "2026-01-01",
            "valid_to": "2027-01-01",
        },
        params={"operation": "register_policy"},
    )


async def test_task_vertical_requires_two_lines_and_verifies():
    block = make_block()
    await _register_active(block, "p1", "public_liability")
    verdict = await block.process(
        {"provider_id": "p1", "vertical": "task", "as_of": "2026-06-01"},
        params={"operation": "verify_coverage"},
    )
    assert verdict["covered"] is False
    assert verdict["covered_lines"] == ["public_liability"]
    assert any(g["line"] == "property_damage" and g["reason"] == "missing" for g in verdict["gaps"])

    # Register the second line -> covered
    await _register_active(block, "p1", "property_damage")
    verdict2 = await block.process(
        {"provider_id": "p1", "vertical": "task", "as_of": "2026-06-01"},
        params={"operation": "verify_coverage"},
    )
    assert verdict2["covered"] is True
    assert verdict2["gaps"] == []


async def test_expired_policy_is_a_gap_not_silent_coverage():
    block = make_block()
    await block.process(
        {
            "provider_id": "p2",
            "policy_id": "pol-expired",
            "line": "public_liability",
            "valid_from": "2024-01-01",
            "valid_to": "2025-01-01",
        },
        params={"operation": "register_policy"},
    )
    verdict = await block.process(
        {"provider_id": "p2", "vertical": "transaction", "as_of": "2026-06-01"},
        params={"operation": "verify_coverage"},
    )
    assert verdict["covered"] is False
    assert any(g["reason"] == "expired_or_not_yet_valid" for g in verdict["gaps"])


async def test_required_coverage_by_vertical():
    block = make_block()
    trip = await block.process({"vertical": "trip"}, params={"operation": "required_coverage"})
    assert trip["required_lines"] == ["auto_liability", "passenger_injury"]

    all_req = await block.process({}, params={"operation": "required_coverage"})
    assert set(all_req["requirements"].keys()) == {"task", "order", "trip", "transaction"}

    bad = await block.process({"vertical": "spaceship"}, params={"operation": "required_coverage"})
    assert bad["status"] == "error"


async def test_incident_intake_attaches_verdict_and_dedupes():
    block = make_block()
    await _register_active(block, "p3", "public_liability")
    await _register_active(block, "p3", "property_damage")
    intake = await block.process(
        {
            "incident_id": "i1",
            "provider_id": "p3",
            "vertical": "task",
            "as_of": "2026-06-01",
            "severity": "high",
        },
        params={"operation": "incident_intake"},
    )
    assert intake["status"] == "success"
    assert intake["covered"] is True
    assert intake["severity"] == "high"

    repeat = await block.process(
        {
            "incident_id": "i1",
            "provider_id": "p3",
            "vertical": "task",
            "as_of": "2026-06-01",
            "severity": "high",
        },
        params={"operation": "incident_intake"},
    )
    assert repeat["idempotent"] is True


async def test_invalid_dates_severity_and_unknown_vertical_fail_loud():
    block = make_block()
    bad_date = await block.process(
        {
            "provider_id": "p4",
            "policy_id": "x",
            "line": "public_liability",
            "valid_from": "not-a-date",
            "valid_to": "2027-01-01",
        },
        params={"operation": "register_policy"},
    )
    assert bad_date["status"] == "error"

    bad_vertical = await block.process(
        {"provider_id": "p4", "vertical": "spaceship", "as_of": "2026-06-01"},
        params={"operation": "verify_coverage"},
    )
    assert bad_vertical["status"] == "error"
    assert "trip" in bad_vertical["error"]

    bad_severity = await block.process(
        {
            "incident_id": "i2",
            "provider_id": "p4",
            "vertical": "task",
            "as_of": "2026-06-01",
            "severity": "catastrophic",
        },
        params={"operation": "incident_intake"},
    )
    assert bad_severity["status"] == "error"
    assert "severity" in bad_severity["error"]

    unknown = await block.process({}, params={"operation": "underwrite"})
    assert unknown["status"] == "error"
    assert "verify_coverage" in unknown["available_operations"]
