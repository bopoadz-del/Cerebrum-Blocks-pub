"""Geolocation Tracking - deterministic position, geofence and ETA math.

The delivery/rideshare tracking core: sequence-numbered position updates,
haversine distance traveled, circular geofences with enter/exit events,
and ETA estimates from distance and speed. Pure math block: no network,
no filesystem, no wall clock - ordering comes from caller-supplied
sequence numbers so every run is reproducible.

Fail-closed on invalid coordinates, out-of-order updates, and unknown
entities/zones. Distances use the same haversine implementation as
task_listing for cross-block consistency.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km between two (lat, lng) points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def valid_lat(lat: Any) -> bool:
    return isinstance(lat, (int, float)) and -90.0 <= lat <= 90.0


def valid_lng(lng: Any) -> bool:
    return isinstance(lng, (int, float)) and -180.0 <= lng <= 180.0


class GeolocationTrackingBlock(UniversalBlock):
    """Deterministic geolocation: updates, geofences, distance, ETA."""

    name = "geolocation_tracking"
    version = "1.0.0"
    description = (
        "Deterministic geolocation tracking: sequence-numbered position "
        "updates, haversine distance traveled, circular geofence enter/exit "
        "events, and ETA estimates from caller-supplied distance and speed."
    )
    layer = 3
    tags = ["domain", "marketplace", "dispatch", "geo", "tracking", "deterministic"]
    requires: List[str] = []
    author = "Cerebrum Team"
    default_config: Dict[str, Any] = {}
    ui_schema = {
        "input": {"type": "json"},
        "output": {"type": "json"},
        "params": [],
        "quick_actions": [],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        # entity_id -> {"positions": [(seq, lat, lng), ...], "events": [...], "distance_km": float}
        self.entities: Dict[str, Dict[str, Any]] = {}
        # zone_id -> {"lat": float, "lng": float, "radius_m": float}
        self.zones: Dict[str, Dict[str, Any]] = {}
        # (entity_id, zone_id) -> inside bool
        self.inside: Dict[tuple, bool] = {}

    # ------------------------------------------------------------------ api
    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**params, **data}
        operation = merged.get("operation") or merged.get("action") or "update_position"

        try:
            if operation == "update_position":
                return self._update_position(merged)
            if operation == "last_position":
                return self._last_position(merged)
            if operation == "distance_traveled":
                return self._distance_traveled(merged)
            if operation == "define_zone":
                return self._define_zone(merged)
            if operation == "zone_check":
                return self._zone_check(merged)
            if operation == "eta":
                return self._eta(merged)
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc), "operation": operation}

        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": [
                "update_position", "last_position", "distance_traveled",
                "define_zone", "zone_check", "eta",
            ],
        }

    # -------------------------------------------------------------- helpers
    def _require(self, data: Dict[str, Any], keys: List[str]) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                return key
        return None

    def _entity(self, entity_id: str) -> Dict[str, Any]:
        record = self.entities.get(entity_id)
        if record is None:
            record = {"positions": [], "events": [], "distance_km": 0.0}
            self.entities[entity_id] = record
        return record

    def _in_zone(self, lat: float, lng: float, zone: Dict[str, Any]) -> bool:
        distance_m = haversine_km(lat, lng, zone["lat"], zone["lng"]) * 1000.0
        return distance_m <= zone["radius_m"]

    # ----------------------------------------------------------- operations
    def _update_position(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["entity_id", "lat", "lng"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        lat, lng = data["lat"], data["lng"]
        if not valid_lat(lat) or not valid_lng(lng):
            return {"status": "error", "error": "invalid_coordinates"}
        try:
            seq = int(data.get("seq", 0))
        except (TypeError, ValueError):
            return {"status": "error", "error": "seq: must be an integer"}

        record = self._entity(data["entity_id"])
        positions = record["positions"]
        if positions and seq <= positions[-1][0]:
            return {
                "status": "error",
                "error": "out_of_order_update",
                "last_seq": positions[-1][0],
            }
        if positions:
            prev_seq, prev_lat, prev_lng = positions[-1]
            segment = haversine_km(prev_lat, prev_lng, float(lat), float(lng))
            record["distance_km"] = round(record["distance_km"] + segment, 4)
        positions.append((seq, float(lat), float(lng)))

        events: List[Dict[str, Any]] = []
        for zone_id, zone in self.zones.items():
            inside = self._in_zone(float(lat), float(lng), zone)
            key = (data["entity_id"], zone_id)
            prior = self.inside.get(key)
            if prior is None:
                self.inside[key] = inside
                if inside:
                    events.append({"seq": seq, "zone_id": zone_id, "event": "enter"})
            elif prior and not inside:
                self.inside[key] = False
                events.append({"seq": seq, "zone_id": zone_id, "event": "exit"})
            elif not prior and inside:
                self.inside[key] = True
                events.append({"seq": seq, "zone_id": zone_id, "event": "enter"})
        record["events"].extend(events)

        return {
            "status": "success",
            "operation": "update_position",
            "entity_id": data["entity_id"],
            "seq": seq,
            "lat": float(lat),
            "lng": float(lng),
            "segment_km": round(segment, 4) if positions and len(positions) > 1 else 0.0,
            "total_km": record["distance_km"],
            "zone_events": events,
        }

    def _last_position(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["entity_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        record = self._entity(data["entity_id"])
        if not record["positions"]:
            return {"status": "error", "error": "no_positions_yet", "entity_id": data["entity_id"]}
        seq, lat, lng = record["positions"][-1]
        return {
            "status": "success",
            "operation": "last_position",
            "entity_id": data["entity_id"],
            "seq": seq,
            "lat": lat,
            "lng": lng,
            "total_km": record["distance_km"],
        }

    def _distance_traveled(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["entity_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        record = self._entity(data["entity_id"])
        return {
            "status": "success",
            "operation": "distance_traveled",
            "entity_id": data["entity_id"],
            "distance_km": record["distance_km"],
            "updates": len(record["positions"]),
        }

    def _define_zone(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["zone_id", "lat", "lng", "radius_m"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        if not valid_lat(data["lat"]) or not valid_lng(data["lng"]):
            return {"status": "error", "error": "invalid_coordinates"}
        try:
            radius_m = float(data["radius_m"])
        except (TypeError, ValueError):
            return {"status": "error", "error": "radius_m: must be a number"}
        if radius_m <= 0:
            return {"status": "error", "error": "radius_m: must be positive"}
        zone = {"lat": float(data["lat"]), "lng": float(data["lng"]), "radius_m": radius_m}
        self.zones[data["zone_id"]] = zone
        return {
            "status": "success",
            "operation": "define_zone",
            "zone_id": data["zone_id"],
            "zone": zone,
        }

    def _zone_check(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["entity_id", "zone_id"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        zone = self.zones.get(data["zone_id"])
        if zone is None:
            return {"status": "error", "error": "zone_not_found"}
        record = self._entity(data["entity_id"])
        if not record["positions"]:
            return {"status": "error", "error": "no_positions_yet"}
        _, lat, lng = record["positions"][-1]
        inside = self._in_zone(lat, lng, zone)
        distance_m = haversine_km(lat, lng, zone["lat"], zone["lng"]) * 1000.0
        return {
            "status": "success",
            "operation": "zone_check",
            "entity_id": data["entity_id"],
            "zone_id": data["zone_id"],
            "inside": inside,
            "distance_m": round(distance_m, 1),
        }

    def _eta(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["distance_km", "speed_kmh"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        try:
            distance_km = float(data["distance_km"])
            speed_kmh = float(data["speed_kmh"])
        except (TypeError, ValueError):
            return {"status": "error", "error": "distance_km and speed_kmh: numbers required"}
        if distance_km < 0:
            return {"status": "error", "error": "distance_km: must be >= 0"}
        if speed_kmh <= 0:
            return {"status": "error", "error": "speed_kmh: must be positive"}
        minutes = (distance_km / speed_kmh) * 60.0
        return {
            "status": "success",
            "operation": "eta",
            "distance_km": distance_km,
            "speed_kmh": speed_kmh,
            "eta_minutes": round(minutes, 1),
        }
