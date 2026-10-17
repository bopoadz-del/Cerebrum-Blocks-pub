"""Tests for the insurance agency hierarchy Store block."""

import pytest

from app.blocks.agency_hierarchy import AgencyHierarchyBlock


@pytest.fixture
def hierarchy_block():
    return AgencyHierarchyBlock()


async def _upsert(block, node):
    return await block.process({"operation": "upsert_node", "node": node})


@pytest.mark.asyncio
async def test_agency_hierarchy_subtree_and_path_to_root(hierarchy_block):
    await _upsert(
        hierarchy_block,
        {
            "id": "carrier-1",
            "role": "carrier",
            "parent_id": None,
            "name": "Northstar Life",
            "effective_from": "2024-01-01",
            "effective_to": None,
            "metadata": {"naic": "10001"},
        },
    )
    await _upsert(
        hierarchy_block,
        {
            "id": "mga-1",
            "role": "mga_fmo",
            "parent_id": "carrier-1",
            "name": "Summit FMO",
            "effective_from": "2024-01-01",
            "effective_to": None,
            "metadata": {},
        },
    )
    await _upsert(
        hierarchy_block,
        {
            "id": "agency-1",
            "role": "agency",
            "parent_id": "mga-1",
            "name": "Pine Agency",
            "effective_from": "2024-02-01",
            "effective_to": None,
            "metadata": {},
        },
    )
    agent_result = await _upsert(
        hierarchy_block,
        {
            "id": "agent-1",
            "role": "agent",
            "parent_id": "agency-1",
            "name": "Jane Producer",
            "effective_from": "2024-03-01",
            "effective_to": None,
            "metadata": {"npn": "123456"},
        },
    )

    assert agent_result["status"] == "success"

    subtree = await hierarchy_block.process(
        {"operation": "get_subtree", "node_id": "carrier-1"}
    )
    assert subtree["status"] == "success"
    assert subtree["count"] == 4
    assert {node["id"] for node in subtree["nodes"]} == {
        "carrier-1",
        "mga-1",
        "agency-1",
        "agent-1",
    }
    assert {"parent_id": "agency-1", "child_id": "agent-1"} in subtree["edges"]

    path = await hierarchy_block.process(
        {"operation": "path_to_root", "node_id": "agent-1"}
    )
    assert path["status"] == "success"
    assert [node["role"] for node in path["path"]] == [
        "agent",
        "agency",
        "mga_fmo",
        "carrier",
    ]


@pytest.mark.asyncio
async def test_agency_hierarchy_allows_unlimited_same_role_depth(hierarchy_block):
    carrier = await _upsert(
        hierarchy_block,
        {
            "id": "carrier-1",
            "role": "carrier",
            "parent_id": None,
            "name": "Northstar Life",
            "effective_from": None,
            "effective_to": None,
            "metadata": {},
        },
    )
    parent_agency = await _upsert(
        hierarchy_block,
        {
            "id": "agency-parent",
            "role": "agency",
            "parent_id": "carrier-1",
            "name": "Parent Agency",
            "effective_from": None,
            "effective_to": None,
            "metadata": {},
        },
    )
    child_agency = await _upsert(
        hierarchy_block,
        {
            "id": "agency-child",
            "role": "agency",
            "parent_id": "agency-parent",
            "name": "Child Agency",
            "effective_from": None,
            "effective_to": None,
            "metadata": {},
        },
    )

    assert carrier["status"] == "success"
    assert parent_agency["status"] == "success"
    assert child_agency["status"] == "success"

    validation = await hierarchy_block.process({"operation": "validate_hierarchy"})
    assert validation["valid"] is True
    assert validation["errors"] == []


@pytest.mark.asyncio
async def test_agency_hierarchy_rejects_invalid_parent_role(hierarchy_block):
    await _upsert(
        hierarchy_block,
        {
            "id": "agent-parent",
            "role": "agent",
            "parent_id": None,
            "name": "Senior Producer",
            "effective_from": None,
            "effective_to": None,
            "metadata": {},
        },
    )

    result = await _upsert(
        hierarchy_block,
        {
            "id": "agency-child",
            "role": "agency",
            "parent_id": "agent-parent",
            "name": "Invalid Agency",
            "effective_from": None,
            "effective_to": None,
            "metadata": {},
        },
    )

    assert result["status"] == "error"
    assert result["valid"] is False
    assert "cannot contain child role" in result["errors"][0]


@pytest.mark.asyncio
async def test_agency_hierarchy_restores_prior_node_on_cycle(hierarchy_block):
    await _upsert(
        hierarchy_block,
        {
            "id": "carrier-1",
            "role": "carrier",
            "parent_id": None,
            "name": "Northstar Life",
            "effective_from": None,
            "effective_to": None,
            "metadata": {},
        },
    )
    await _upsert(
        hierarchy_block,
        {
            "id": "agency-parent",
            "role": "agency",
            "parent_id": "carrier-1",
            "name": "Parent Agency",
            "effective_from": None,
            "effective_to": None,
            "metadata": {},
        },
    )
    await _upsert(
        hierarchy_block,
        {
            "id": "agency-child",
            "role": "agency",
            "parent_id": "agency-parent",
            "name": "Child Agency",
            "effective_from": None,
            "effective_to": None,
            "metadata": {},
        },
    )

    cycle_result = await _upsert(
        hierarchy_block,
        {
            "id": "agency-parent",
            "role": "agency",
            "parent_id": "agency-child",
            "name": "Parent Agency",
            "effective_from": None,
            "effective_to": None,
            "metadata": {},
        },
    )

    assert cycle_result["status"] == "error"
    assert any("cycle" in error for error in cycle_result["errors"])

    path = await hierarchy_block.process(
        {"operation": "path_to_root", "node_id": "agency-child"}
    )
    assert path["status"] == "success"
    assert [node["id"] for node in path["path"]] == [
        "agency-child",
        "agency-parent",
        "carrier-1",
    ]
    assert hierarchy_block._nodes["agency-parent"]["parent_id"] == "carrier-1"


@pytest.mark.asyncio
async def test_agency_hierarchy_validate_reports_bad_dates(hierarchy_block):
    result = await _upsert(
        hierarchy_block,
        {
            "id": "carrier-1",
            "role": "carrier",
            "parent_id": None,
            "name": "Northstar Life",
            "effective_from": "2025-01-01",
            "effective_to": "2024-01-01",
            "metadata": {},
        },
    )

    assert result["status"] == "error"
    assert "effective_to cannot be before effective_from" in result["errors"][0]
