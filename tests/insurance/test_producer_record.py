"""Tests for the insurance producer record Store block."""

import pytest

from app.blocks.producer_record import ProducerRecordBlock


@pytest.fixture
def producer_block():
    return ProducerRecordBlock()


async def _upsert(block, producer):
    return await block.process({"operation": "upsert", "producer": producer})


def _producer(producer_id, agency_id="agency-1", status="active", expires="2027-12-31"):
    return {
        "producer_id": producer_id,
        "name": f"Producer {producer_id}",
        "licenses": [
            {
                "jurisdiction": "tx",
                "number": f"LIC-{producer_id}",
                "status": "active",
                "expires": expires,
            }
        ],
        "agency_id": agency_id,
        "status": status,
        "appointed_carriers": ["carrier-1"],
    }


@pytest.mark.asyncio
async def test_producer_record_upsert_and_get(producer_block):
    upsert = await _upsert(producer_block, _producer("prod-1"))

    assert upsert["status"] == "success"
    assert upsert["producer"]["producer_id"] == "prod-1"
    assert upsert["producer"]["licenses"][0]["jurisdiction"] == "TX"

    result = await producer_block.process(
        {"operation": "get", "producer_id": "prod-1"}
    )
    assert result["status"] == "success"
    assert result["producer"]["agency_id"] == "agency-1"
    assert result["producer"]["appointed_carriers"] == ["carrier-1"]


@pytest.mark.asyncio
async def test_producer_record_list_by_agency(producer_block):
    await _upsert(producer_block, _producer("prod-1", agency_id="agency-1"))
    await _upsert(producer_block, _producer("prod-2", agency_id="agency-1", status="terminated"))
    await _upsert(producer_block, _producer("prod-3", agency_id="agency-2"))

    all_agency = await producer_block.process(
        {"operation": "list_by_agency", "agency_id": "agency-1"}
    )
    assert all_agency["status"] == "success"
    assert [producer["producer_id"] for producer in all_agency["producers"]] == [
        "prod-1",
        "prod-2",
    ]

    active_only = await producer_block.process(
        {
            "operation": "list_by_agency",
            "agency_id": "agency-1",
            "include_inactive": False,
        }
    )
    assert active_only["count"] == 1
    assert active_only["producers"][0]["producer_id"] == "prod-1"


@pytest.mark.asyncio
async def test_producer_record_license_status_active_and_expired(producer_block):
    await _upsert(producer_block, _producer("active-prod", expires="2027-12-31"))
    await _upsert(producer_block, _producer("expired-prod", expires="2023-12-31"))

    active = await producer_block.process(
        {
            "operation": "license_status",
            "producer_id": "active-prod",
            "as_of": "2026-01-01",
        }
    )
    assert active["status"] == "success"
    assert active["license_status"] == "active"
    assert active["licenses"][0]["is_active"] is True

    expired = await producer_block.process(
        {
            "operation": "license_status",
            "producer_id": "expired-prod",
            "as_of": "2026-01-01",
        }
    )
    assert expired["license_status"] == "expired"
    assert expired["licenses"][0]["is_expired"] is True


@pytest.mark.asyncio
async def test_producer_record_requires_license_fields(producer_block):
    result = await _upsert(
        producer_block,
        {
            "producer_id": "prod-1",
            "name": "Producer One",
            "licenses": [{"jurisdiction": "CA", "status": "active"}],
            "agency_id": "agency-1",
            "status": "active",
            "appointed_carriers": [],
        },
    )

    assert result["status"] == "error"
    assert "licenses[0].number is required" in result["errors"]
