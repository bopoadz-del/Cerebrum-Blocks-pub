"""Payload-asserting tests for the geolocation_tracking block.

Assertions target tracking payloads (haversine segments, totals, geofence
enter/exit events, out-of-order refusals, ETA math) so a control-delete
gut of process() turns them red.
"""

from app.blocks.geolocation_tracking import GeolocationTrackingBlock, haversine_km


def make_block():
    return GeolocationTrackingBlock()


async def test_haversine_known_distance():
    # Manhattan to Jersey City ~6.3 km (matches task_listing's measured value)
    d = haversine_km(40.7128, -74.0060, 40.7282, -74.0778)
    assert 5.0 < d < 8.0


async def test_position_updates_accumulate_distance():
    block = make_block()
    await block.process(
        {"entity_id": "e1", "seq": 1, "lat": 40.7128, "lng": -74.0060},
        params={"operation": "update_position"},
    )
    second = await block.process(
        {"entity_id": "e1", "seq": 2, "lat": 40.7282, "lng": -74.0778},
        params={"operation": "update_position"},
    )
    assert second["status"] == "success"
    assert 5.0 < second["segment_km"] < 8.0
    assert second["total_km"] == second["segment_km"]

    distance = await block.process(
        {"entity_id": "e1"}, params={"operation": "distance_traveled"}
    )
    assert distance["updates"] == 2
    assert 5.0 < distance["distance_km"] < 8.0


async def test_out_of_order_and_invalid_updates_refused():
    block = make_block()
    await block.process(
        {"entity_id": "e2", "seq": 5, "lat": 10.0, "lng": 10.0},
        params={"operation": "update_position"},
    )
    stale = await block.process(
        {"entity_id": "e2", "seq": 3, "lat": 11.0, "lng": 11.0},
        params={"operation": "update_position"},
    )
    assert stale["status"] == "error"
    assert stale["error"] == "out_of_order_update"
    assert stale["last_seq"] == 5

    bad = await block.process(
        {"entity_id": "e2", "seq": 6, "lat": 91.0, "lng": 11.0},
        params={"operation": "update_position"},
    )
    assert bad["status"] == "error"
    assert bad["error"] == "invalid_coordinates"


async def test_geofence_enter_and_exit_events():
    block = make_block()
    # Zone centered on Manhattan, radius 3 km
    await block.process(
        {"zone_id": "z1", "lat": 40.7128, "lng": -74.0060, "radius_m": 3000},
        params={"operation": "define_zone"},
    )
    # First update inside the zone -> enter event
    inside = await block.process(
        {"entity_id": "e3", "seq": 1, "lat": 40.7128, "lng": -74.0060},
        params={"operation": "update_position"},
    )
    assert inside["zone_events"][0]["event"] == "enter"
    assert inside["zone_events"][0]["zone_id"] == "z1"

    # Move to Jersey City (~6.3 km) -> exit event
    outside = await block.process(
        {"entity_id": "e3", "seq": 2, "lat": 40.7282, "lng": -74.0778},
        params={"operation": "update_position"},
    )
    assert outside["zone_events"][0]["event"] == "exit"

    check = await block.process(
        {"entity_id": "e3", "zone_id": "z1"}, params={"operation": "zone_check"}
    )
    assert check["inside"] is False
    assert check["distance_m"] > 6000


async def test_eta_math_and_refusals():
    block = make_block()
    eta = await block.process(
        {"distance_km": 12.0, "speed_kmh": 40.0}, params={"operation": "eta"}
    )
    assert eta["status"] == "success"
    assert eta["eta_minutes"] == 18.0

    zero_speed = await block.process(
        {"distance_km": 5.0, "speed_kmh": 0.0}, params={"operation": "eta"}
    )
    assert zero_speed["status"] == "error"
    assert zero_speed["error"] == "speed_kmh: must be positive"

    negative = await block.process(
        {"distance_km": -1.0, "speed_kmh": 30.0}, params={"operation": "eta"}
    )
    assert negative["status"] == "error"


async def test_last_position_and_unknown_zone():
    block = make_block()
    await block.process(
        {"entity_id": "e4", "seq": 1, "lat": 1.0, "lng": 2.0},
        params={"operation": "update_position"},
    )
    last = await block.process({"entity_id": "e4"}, params={"operation": "last_position"})
    assert last["seq"] == 1
    assert last["lat"] == 1.0
    assert last["lng"] == 2.0

    ghost = await block.process(
        {"entity_id": "e4", "zone_id": "ghost-zone"}, params={"operation": "zone_check"}
    )
    assert ghost["status"] == "error"
    assert ghost["error"] == "zone_not_found"

    unknown = await block.process({}, params={"operation": "warp"})
    assert unknown["status"] == "error"
    assert "update_position" in unknown["available_operations"]
