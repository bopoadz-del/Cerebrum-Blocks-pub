"""Payload-asserting tests for the task_listing block.

Assertions target listing payloads, validation errors, haversine
distances, filters and price bands so a control-delete gut of ``process()``
turns them red.
"""

from app.blocks.task_listing import TaskListingBlock, CATEGORIES, PRICE_BANDS


def make_block():
    return TaskListingBlock()


VALID_LISTING = {
    "title": "Deliver a parcel to Brooklyn",
    "description": "Small parcel, 2 kg, pick up in Manhattan.",
    "category": "delivery",
    "location": {"lat": 40.7128, "lng": -74.0060},
    "budget": {"min": 10, "max": 40},
}


async def test_create_valid_listing_is_deterministic():
    block = make_block()
    first = await block.process({"listing": VALID_LISTING}, params={"operation": "create"})
    assert first["status"] == "success", first
    assert first["listing_id"]
    assert first["listing"]["status"] == "open"
    assert first["listing"]["category"] == "delivery"

    second = await block.process({"listing": VALID_LISTING}, params={"operation": "create"})
    assert second["listing_id"] == first["listing_id"]


async def test_validate_reports_every_violation():
    block = make_block()
    result = await block.process(
        {
            "listing": {
                "title": "",
                "category": "skydiving",
                "location": {"lat": 91.0, "lng": -74.0},
            }
        },
        params={"operation": "validate"},
    )
    assert result["valid"] is False
    joined = " | ".join(result["errors"])
    assert "title" in joined
    assert "category" in joined
    assert "location.lat" in joined


async def test_create_rejects_invalid_and_names_errors():
    block = make_block()
    result = await block.process(
        {"listing": {"title": "x", "category": "delivery", "location": {"address": ""}}},
        params={"operation": "create"},
    )
    assert result["status"] == "error"
    assert result["error"] == "validation_failed"
    assert any("location" in e for e in result["errors"])


async def test_distance_match_filters_by_radius():
    block = make_block()
    # NYC listing
    await block.process({"listing": VALID_LISTING}, params={"operation": "create"})
    # Worker in Jersey City (~6.3 km from the listing per haversine)
    near = await block.process(
        {"worker": {"lat": 40.7282, "lng": -74.0778}, "radius_km": 25},
        params={"operation": "distance_match"},
    )
    assert near["status"] == "success"
    assert near["count"] == 1
    assert 5.0 < near["matched"][0]["distance_km"] < 8.0

    # Worker in Los Angeles is outside the radius
    far = await block.process(
        {"worker": {"lat": 34.0522, "lng": -118.2437}, "radius_km": 25},
        params={"operation": "distance_match"},
    )
    assert far["count"] == 0


async def test_filter_search_by_category_keyword_and_budget():
    block = make_block()
    await block.process({"listing": VALID_LISTING}, params={"operation": "create"})
    await block.process(
        {
            "listing": {
                "title": "Clean a two-bedroom flat",
                "category": "cleaning",
                "location": {"lat": 40.7128, "lng": -74.0060},
                "budget": {"min": 60, "max": 120},
            }
        },
        params={"operation": "create"},
    )
    by_cat = await block.process({"category": "cleaning"}, params={"operation": "filter_search"})
    assert by_cat["count"] == 1
    assert by_cat["results"][0]["category"] == "cleaning"

    by_keyword = await block.process({"keyword": "parcel"}, params={"operation": "filter_search"})
    assert by_keyword["count"] == 1
    assert by_keyword["results"][0]["listing_id"]

    by_budget = await block.process({"budget_max": 50}, params={"operation": "filter_search"})
    assert by_budget["count"] == 1  # only the 10..40 delivery task


async def test_suggest_price_band_and_duration_scaling():
    block = make_block()
    band = await block.process(
        {"category": "cleaning"}, params={"operation": "suggest_price_band"}
    )
    assert band["status"] == "success"
    assert band["band"]["min"] == PRICE_BANDS["cleaning"]["min"]
    assert band["band"]["max"] == PRICE_BANDS["cleaning"]["max"]
    assert band["band"]["source"] == "embedded"

    scaled = await block.process(
        {"category": "cleaning", "duration_hours": 2},
        params={"operation": "suggest_price_band"},
    )
    assert scaled["band"]["min"] == 80
    assert scaled["band"]["max"] == 400


async def test_unknown_category_and_operation_fail_loud():
    block = make_block()
    bad_cat = await block.process(
        {"category": "skydiving"}, params={"operation": "suggest_price_band"}
    )
    assert bad_cat["status"] == "error"
    assert "cleaning" in bad_cat["error"]

    bad_op = await block.process({}, params={"operation": "transmogrify"})
    assert bad_op["status"] == "error"
    assert "create" in bad_op["available_operations"]


async def test_worker_without_coordinates_is_refused():
    block = make_block()
    result = await block.process(
        {"worker": {"name": "ghost"}, "radius_km": 10},
        params={"operation": "distance_match"},
    )
    assert result["status"] == "error"
    assert "worker" in result["error"]
