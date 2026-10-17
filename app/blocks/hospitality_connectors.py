"""Hospitality Enterprise Connectors â€” fixture/live dual-mode framework,
ported from <private-repo> ``connectors/base.py`` +
``connectors/{opera,micros,maximo,grms,gaming_cms,loyalty_lms}.py`` +
``hotelops/event_bus.py``.

Ported exactly:
- BaseConnector connect -> fetch -> normalise -> emit pipeline with
  automatic fixture-vs-live switching: live mode only when fixture_mode is
  disabled AND every live_env_key is configured; otherwise the vendored
  fixture pack is served. A connector with neither refuses.
- fetch_live() is an httpx GET with raise_for_status(); live_url() refuses
  (ConnectorError) when the base URL is empty, so an unconfigured live
  system fails closed instead of dialing a garbage URL.
- HotelEvent topics per system: Opera reservations->guest.booking.reservation,
  in_house->ops.pms.in_house, housekeeping->ops.pms.housekeeping;
  Micros checks->guest.folio.charge; Maximo assets->ops.engineering.asset
  (with the aconex/procore/bim source_system out-of-scope refusal),
  workorders->ops.cmms.workorder; GRMS config judged by the donor's GRMS
  evidence branch (INV-GRMS-CERT-NE-CONFIG / INV-GRMS-ROOM-MAP, cloned from
  reasoning/evidence.py with the invalidity remediation text); gaming CMS
  comps and loyalty LMS profiles.
- The in-process EventBus (hotelops/event_bus.py): typed HotelEvent with
  publish/subscribe/history. Fixture records are vendored inline from the
  donor's fixtures/connectors/*.json.
"""
from __future__ import annotations

import json
import threading
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

import httpx

from app.core.universal_base import UniversalBlock
from app.core.http_errors import mark_unavailable


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "hospitality_connectors", "status": status, "result": result, "error": error, "detail": detail}


# ---------------------------------------------------------------- hotelops/event_bus.py

SURFACES = {"ops", "guest", "both"}


@dataclass
class HotelEvent:
    topic: str
    surface: str
    source: str
    payload: Dict[str, Any]
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    evidence_class: Optional[str] = None
    verdict: Optional[str] = None

    def __post_init__(self) -> None:
        if self.surface not in SURFACES:
            raise ValueError(f"surface must be ops|guest|both, got {self.surface!r}")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "ts": self.ts,
            "topic": self.topic,
            "surface": self.surface,
            "source": self.source,
            "payload": self.payload,
            "evidence_class": self.evidence_class,
            "verdict": self.verdict,
        }


Handler = Callable[[HotelEvent], None]


class EventBus:
    """In-process bus with wildcard subscribe. Redis is optional at deploy time."""

    def __init__(self) -> None:
        self._subs: Dict[str, List[Handler]] = defaultdict(list)
        self._history: List[HotelEvent] = []
        self._lock = threading.Lock()

    def publish(self, event: HotelEvent | Dict[str, Any]) -> HotelEvent:
        if isinstance(event, dict):
            event = HotelEvent(**{k: v for k, v in event.items() if k in HotelEvent.__dataclass_fields__})
        with self._lock:
            self._history.append(event)
            handlers = list(self._subs.get(event.topic, []))
            for pattern, hs in self._subs.items():
                if pattern.endswith("*") and event.topic.startswith(pattern[:-1]):
                    handlers.extend(hs)
                if pattern == "*" or pattern == event.surface + ".*":
                    handlers.extend(hs)
        for handler in handlers:
            handler(event)
        return event

    def subscribe(self, topic: str, handler: Handler) -> None:
        with self._lock:
            self._subs[topic].append(handler)

    def history(
        self,
        *,
        surface: Optional[str] = None,
        topic_prefix: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            rows = list(self._history)
        if surface:
            rows = [e for e in rows if e.surface in {surface, "both"}]
        if topic_prefix:
            rows = [e for e in rows if e.topic.startswith(topic_prefix)]
        return [e.as_dict() for e in rows[-limit:]]

    def clear(self) -> None:
        with self._lock:
            self._history.clear()


# ---------------------------------------------------------------- reasoning/guard.py (subset used by maximo)

FORBIDDEN_SOURCES = {"aconex", "procore", "bim", "bim_ifc", "navisworks", "revit"}


class GuardError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def guard_request(
    *,
    market: Optional[str] = None,
    source_system: Optional[str] = None,
    asset_sources: Optional[Iterable[str]] = None,
    construction_pm: bool = False,
    demo_only: bool = False,
) -> None:
    if construction_pm:
        raise GuardError(
            "construction_pm_out_of_scope",
            "Aconex/Procore/BIM parse is out of scope. Use CSV/JSON/CMMS ingest.",
        )
    sources = [source_system] if source_system else []
    if asset_sources:
        sources.extend(asset_sources)
    for src in sources:
        if src and src.lower() in FORBIDDEN_SOURCES:
            raise GuardError(
                "construction_pm_out_of_scope",
                f"Source {src!r} is construction-PM/BIM and is refused.",
            )


# ---------------------------------------------------------------- reasoning/evidence.py GRMS branch

def _grms_evidence(raw: Dict[str, Any]) -> Dict[str, Any]:
    if raw.get("grms_cert_matches_config") is False:
        return {
            "evidence_class": "Unprovable",
            "verdict": "UNPROVABLE",
            "reasons": ["GRMS certificate does not match the live room-by-room configuration."],
            "invalidity_ids": ["INV-GRMS-CERT-NE-CONFIG"],
            "remediation": ["Diff cert room list against live controller map; remap before M12 gate."],
        }
    if raw.get("room_map_complete") is False or raw.get("room_map_complete") is None:
        return {
            "evidence_class": "Unprovable",
            "verdict": "UNPROVABLE",
            "reasons": ["GRMS configuration is missing a complete room→controller map."],
            "invalidity_ids": ["INV-GRMS-ROOM-MAP"],
            "remediation": ["Load complete room→controller map."],
        }
    if raw.get("grms_cert_matches_config") is True and raw.get("room_map_complete") is True:
        return {"evidence_class": "A", "verdict": "PASS", "reasons": ["GRMS cert matches live room map."]}
    return {"evidence_class": "A", "verdict": "PASS", "reasons": ["GRMS room map is complete."]}


# ---------------------------------------------------------------- fixtures/connectors/*.json (vendored)

FIXTURES: Dict[str, Dict[str, Any]] = {
    "opera": {
        "reservations": {"records": [
            {"id": "R-1001", "confirmation_id": "CNF-DXB-1001", "guest_id": "G-AYA", "arrival": "2026-09-18", "departure": "2026-09-21", "room_type": "king", "status": "reserved", "rate_code": "BAR", "market": "uae"},
            {"id": "R-1002", "confirmation_id": "CNF-GEN-2044", "guest_id": "G-MARCO", "arrival": "2026-09-19", "departure": "2026-09-22", "room_type": "suite", "status": "reserved", "rate_code": "CORP", "market": "generic"},
            {"id": "R-1003", "confirmation_id": "CNF-DXB-1003", "guest_id": "G-NOOR", "arrival": "2026-09-12", "departure": "2026-09-14", "room_type": "twin", "status": "in_house", "rate_code": "LOY-GLD", "market": "uae"},
        ]},
        "housekeeping": {"records": [
            {"id": "HK-1204", "room": "1204", "hk_status": "inspected"},
            {"id": "HK-0808", "room": "0808", "hk_status": "dirty"},
        ]},
        "in_house": {"records": [
            {"id": "IH-1", "room": "1204", "guest_id": "G-NOOR", "status": "in_house", "vip": True},
            {"id": "IH-2", "room": "0808", "guest_id": "G-SAM", "status": "in_house", "vip": False},
        ]},
    },
    "micros": {
        "checks": {"records": [
            {"id": "CHK-77", "check_id": "CHK-77", "outlet": "lobby_cafe", "amount": 128.5, "room": "1204", "covers": 2, "closed": True},
        ]},
    },
    "maximo": {
        "assets": {"records": [
            {"asset_id": "FP-01", "asset_type": "fire_pump", "serial_number": "AFP-77821", "location": "B1-PUMP-ROOM", "manufacturer": "Armstrong", "install_date": "2026-03-12", "source_system": "maximo", "evidence_class": "A", "statutory_flag": True},
            {"asset_id": "EL-03", "asset_type": "elevator", "serial_number": "OTS-4401", "location": "CORE-A", "manufacturer": "Otis", "install_date": "2026-04-02", "source_system": "maximo", "evidence_class": "B", "statutory_flag": True},
            {"asset_id": "AHU-12", "asset_type": "ahu", "serial_number": "CAR-991", "location": "L12-PLANT", "manufacturer": "Carrier", "install_date": "2026-05-01", "source_system": "csv_upload", "evidence_class": "C", "statutory_flag": False},
        ]},
        "workorders": {"records": [
            {"id": "WO-501", "wo": "WO-501", "asset_id": "FP-01", "status": "open", "task": "monthly_flow_test"},
        ]},
    },
    "grms": {
        "config": {"rooms": [
            {"room": "1204", "controller_id": "CTRL-1"},
            {"room": "1205", "controller_id": "CTRL-2"},
        ]},
        "config_incomplete": {"rooms": [
            {"room": "1204", "controller_id": "CTRL-1"},
            {"room": "1205"},
        ]},
        "rooms": {"records": [
            {"room": "1204", "dnd": False, "occupied": True},
            {"room": "1205", "dnd": True, "occupied": False},
        ]},
    },
    "gaming_cms": {
        "players": {"records": [
            {"id": "P-9", "player_id": "P-9", "comp_balance": 320.0, "host": "h1", "linked_reservation": "CNF-DXB-1001"},
        ]},
    },
    "loyalty_lms": {
        "profiles": {"records": [
            {"id": "L-4", "profile_id": "L-4", "tier": "gold", "nights": 42, "points": 12800, "market": "uae"},
        ]},
    },
}


# ---------------------------------------------------------------- connectors/base.py

class ConnectorError(RuntimeError):
    pass


class _ConnectorSettings:
    """Dict-backed stand-in for hotelops.settings.Settings.

    Same contract as the donor: live_enabled(*keys) is False while
    fixture_mode is set, otherwise every named key must be non-empty.
    """

    def __init__(self, values: Dict[str, Any]) -> None:
        self._values = {k: v for k, v in (values or {}).items()}

    def __getattr__(self, name: str) -> Any:
        if name in self._values:
            return self._values[name]
        if name == "fixture_mode":
            return True
        return ""

    def live_enabled(self, *keys: str) -> bool:
        if self.fixture_mode:
            return False
        return all(bool(getattr(self, k, "")) for k in keys)


class BaseConnector(ABC):
    name: str
    source: str
    surface: str = "both"
    live_env_keys: tuple = ()

    def __init__(self, settings: _ConnectorSettings, bus: EventBus) -> None:
        self.settings = settings
        self.bus = bus
        self._connected = False
        self._mode = "fixture"

    def connect(self) -> Dict[str, Any]:
        if self.settings.live_enabled(*self.live_env_keys):
            self._mode = "live"
            self._connected = True
            return {"status": "connected", "mode": "live", "connector": self.name}
        if self.name not in FIXTURES:
            raise ConnectorError(f"No fixture pack for {self.name}")
        self._mode = "fixture"
        self._connected = True
        return {"status": "connected", "mode": "fixture", "connector": self.name}

    def fetch(self, resource: str, **params: Any) -> Any:
        if not self._connected:
            self.connect()
        if self._mode == "live":
            return self.fetch_live(resource, **params)
        return self.fetch_fixture(resource, **params)

    def fetch_fixture(self, resource: str, **params: Any) -> Any:
        pack = FIXTURES.get(self.name) or {}
        if resource not in pack:
            raise ConnectorError(f"Fixture {resource}.json missing for {self.name}")
        data = json.loads(json.dumps(pack[resource]))
        record_id = params.get("id")
        if record_id and isinstance(data, dict) and "records" in data:
            for row in data["records"]:
                if str(row.get("id")) == str(record_id):
                    return row
            raise ConnectorError(f"{resource} id={record_id} not in {self.name} fixtures")
        return data

    def fetch_live(self, resource: str, **params: Any) -> Any:
        url = self.live_url(resource)
        headers = self.live_headers()
        resp = httpx.get(url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def live_url(self, resource: str) -> str:
        raise mark_unavailable(ConnectorError(f"{self.name} live URL not configured"))

    def live_headers(self) -> Dict[str, str]:
        raise ConnectorError(f"{self.name} has no live integration configured")

    @abstractmethod
    def normalise(self, resource: str, raw: Any) -> List[HotelEvent]:
        ...

    def emit(self, events: List[HotelEvent]) -> List[Dict[str, Any]]:
        return [self.bus.publish(event).as_dict() for event in events]

    def ingest(self, resource: str, **params: Any) -> Dict[str, Any]:
        raw = self.fetch(resource, **params)
        events = self.normalise(resource, raw)
        published = self.emit(events)
        return {
            "connector": self.name,
            "mode": self._mode,
            "resource": resource,
            "emitted": len(published),
            "events": published,
        }


# ---------------------------------------------------------------- connectors/{opera,micros,maximo,grms,gaming_cms,loyalty_lms}.py

class OperaConnector(BaseConnector):
    name = "opera"
    source = "opera_pms"
    live_env_keys = ("opera_base_url", "opera_client_id", "opera_client_secret")

    def live_url(self, resource: str) -> str:
        base = self.settings.opera_base_url
        if not base:
            raise mark_unavailable(ConnectorError("opera live URL not configured"))
        return f"{base.rstrip('/')}/v1/{resource}"

    def live_headers(self) -> Dict[str, str]:
        return {"X-Client-Id": self.settings.opera_client_id, "X-Client-Secret": self.settings.opera_client_secret}

    def normalise(self, resource: str, raw: Any) -> List[HotelEvent]:
        records = raw.get("records", raw if isinstance(raw, list) else [raw])
        events: List[HotelEvent] = []
        for row in records:
            if resource == "reservations":
                topic = "guest.booking.reservation"
                payload = {
                    "confirmation_id": row.get("confirmation_id") or row.get("id"),
                    "guest_id": row.get("guest_id"),
                    "arrival": row.get("arrival"),
                    "departure": row.get("departure"),
                    "room_type": row.get("room_type"),
                    "status": row.get("status"),
                    "rate_code": row.get("rate_code"),
                    "market": row.get("market", "uae"),
                }
                surface = "guest"
            elif resource == "in_house":
                topic = "ops.pms.in_house"
                payload = {
                    "room": row.get("room"),
                    "guest_id": row.get("guest_id"),
                    "status": row.get("status"),
                    "vip": row.get("vip", False),
                }
                surface = "ops"
            elif resource == "housekeeping":
                topic = "ops.pms.housekeeping"
                payload = {"room": row.get("room"), "hk_status": row.get("hk_status")}
                surface = "ops"
            else:
                topic = f"connector.pms.{resource}"
                payload = dict(row)
                surface = "both"
            events.append(HotelEvent(topic=topic, surface=surface, source=self.source, payload=payload))
        return events


class MicrosConnector(BaseConnector):
    name = "micros"
    source = "micros_simphony"
    live_env_keys = ("micros_base_url", "micros_api_key")

    def live_url(self, resource: str) -> str:
        base = self.settings.micros_base_url
        if not base:
            raise mark_unavailable(ConnectorError("micros live URL not configured"))
        return f"{base.rstrip('/')}/{resource}"

    def live_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.micros_api_key}"}

    def normalise(self, resource: str, raw: Any) -> List[HotelEvent]:
        records = raw.get("records", raw if isinstance(raw, list) else [raw])
        events = []
        for row in records:
            events.append(
                HotelEvent(
                    topic="guest.folio.charge" if resource == "checks" else f"connector.pos.{resource}",
                    surface="guest" if resource == "checks" else "ops",
                    source=self.source,
                    payload={
                        "check_id": row.get("check_id") or row.get("id"),
                        "outlet": row.get("outlet"),
                        "amount": row.get("amount"),
                        "room": row.get("room"),
                        "covers": row.get("covers"),
                        "closed": row.get("closed", False),
                    },
                )
            )
        return events


class MaximoConnector(BaseConnector):
    name = "maximo"
    source = "maximo_cmms"
    live_env_keys = ("maximo_base_url", "maximo_api_key")

    def live_url(self, resource: str) -> str:
        base = self.settings.maximo_base_url
        if not base:
            raise mark_unavailable(ConnectorError("maximo live URL not configured"))
        return f"{base.rstrip('/')}/os/{resource}"

    def live_headers(self) -> Dict[str, str]:
        return {"apikey": self.settings.maximo_api_key}

    def normalise(self, resource: str, raw: Any) -> List[HotelEvent]:
        if resource == "assets":
            guard_request(source_system="maximo")
            records = raw.get("records", raw if isinstance(raw, list) else [raw])
            for row in records:
                src = (row.get("source_system") or "maximo").lower()
                if src in {"aconex", "procore", "bim", "bim_ifc"}:
                    raise ConnectorError(f"Asset {row.get('asset_id')} source {src} is out of scope")
            return [
                HotelEvent(
                    topic="ops.engineering.asset",
                    surface="ops",
                    source=self.source,
                    payload={
                        "asset_id": row.get("asset_id") or row.get("id"),
                        "asset_type": row.get("asset_type"),
                        "serial_number": row.get("serial_number"),
                        "location": row.get("location"),
                        "evidence_class": row.get("evidence_class"),
                        "statutory_flag": row.get("statutory_flag", False),
                        "source_system": row.get("source_system", "maximo"),
                    },
                    evidence_class=row.get("evidence_class"),
                )
                for row in records
            ]
        records = raw.get("records", raw if isinstance(raw, list) else [raw])
        return [
            HotelEvent(
                topic="ops.cmms.workorder",
                surface="ops",
                source=self.source,
                payload={"wo": row.get("wo") or row.get("id"), "asset_id": row.get("asset_id"), "status": row.get("status")},
            )
            for row in records
        ]


class GRMSConnector(BaseConnector):
    name = "grms"
    source = "grms"
    live_env_keys = ("grms_base_url", "grms_api_key")

    def live_url(self, resource: str) -> str:
        base = self.settings.grms_base_url
        if not base:
            raise mark_unavailable(ConnectorError("grms live URL not configured"))
        return f"{base.rstrip('/')}/{resource}"

    def live_headers(self) -> Dict[str, str]:
        return {"X-Api-Key": self.settings.grms_api_key}

    def normalise(self, resource: str, raw: Any) -> List[HotelEvent]:
        if resource == "config":
            rooms = raw.get("rooms") or []
            mapped = sum(1 for r in rooms if r.get("controller_id"))
            complete = bool(rooms) and mapped == len(rooms)
            judged = _grms_evidence(
                {
                    "asset_type": "grms",
                    "room_map_complete": complete,
                    "documents": ["room_map"] if complete else [],
                }
            )
            return [
                HotelEvent(
                    topic="ops.engineering.grms_config",
                    surface="ops",
                    source=self.source,
                    payload={
                        "rooms": len(rooms),
                        "mapped": mapped,
                        "room_map_complete": complete,
                        **judged,
                    },
                    evidence_class=judged["evidence_class"],
                    verdict=judged["verdict"],
                )
            ]
        records = raw.get("records", raw if isinstance(raw, list) else [raw])
        return [
            HotelEvent(
                topic="ops.grms.room",
                surface="ops",
                source=self.source,
                payload={"room": row.get("room"), "dnd": row.get("dnd"), "occupied": row.get("occupied")},
            )
            for row in records
        ]


class GamingCMSConnector(BaseConnector):
    name = "gaming_cms"
    source = "gaming_cms"
    live_env_keys = ("gaming_cms_base_url", "gaming_cms_api_key")

    def live_url(self, resource: str) -> str:
        base = self.settings.gaming_cms_base_url
        if not base:
            raise mark_unavailable(ConnectorError("gaming_cms live URL not configured"))
        return f"{base.rstrip('/')}/{resource}"

    def live_headers(self) -> Dict[str, str]:
        return {"X-Api-Key": self.settings.gaming_cms_api_key}

    def normalise(self, resource: str, raw: Any) -> List[HotelEvent]:
        records = raw.get("records", raw if isinstance(raw, list) else [raw])
        return [
            HotelEvent(
                topic="guest.gaming.comp",
                surface="guest",
                source=self.source,
                payload={
                    "player_id": row.get("player_id") or row.get("id"),
                    "comp_balance": row.get("comp_balance", 0),
                    "host": row.get("host"),
                    "linked_reservation": row.get("linked_reservation"),
                },
            )
            for row in records
        ]


class LoyaltyLMSConnector(BaseConnector):
    name = "loyalty_lms"
    source = "loyalty_lms"
    live_env_keys = ("loyalty_lms_base_url", "loyalty_lms_api_key")

    def live_url(self, resource: str) -> str:
        base = self.settings.loyalty_lms_base_url
        if not base:
            raise mark_unavailable(ConnectorError("loyalty_lms live URL not configured"))
        return f"{base.rstrip('/')}/{resource}"

    def live_headers(self) -> Dict[str, str]:
        return {"X-Api-Key": self.settings.loyalty_lms_api_key}

    def normalise(self, resource: str, raw: Any) -> List[HotelEvent]:
        records = raw.get("records", raw if isinstance(raw, list) else [raw])
        events = []
        for row in records:
            events.append(
                HotelEvent(
                    topic="guest.loyalty.profile",
                    surface="guest",
                    source=self.source,
                    payload={
                        "profile_id": row.get("profile_id") or row.get("id"),
                        "tier": row.get("tier"),
                        "nights": row.get("nights"),
                        "points": row.get("points"),
                        "market": row.get("market", "uae"),
                    },
                )
            )
        return events


CONNECTOR_CLASSES = {
    "opera": OperaConnector,
    "micros": MicrosConnector,
    "maximo": MaximoConnector,
    "grms": GRMSConnector,
    "gaming_cms": GamingCMSConnector,
    "loyalty_lms": LoyaltyLMSConnector,
}


class HospitalityConnectorsBlock(UniversalBlock):
    """Fixture/live dual-mode hospitality connectors ported from <private-repo>."""

    name = "hospitality_connectors"
    version = "1.0.0"
    description = (
        "Hospitality enterprise connectors ported from <private-repo> "
        "connectors/base.py + connectors/{opera,micros,maximo,grms,gaming_cms,"
        "loyalty_lms}.py + hotelops/event_bus.py (real): connect->fetch->"
        "normalise->emit with automatic fixture-vs-live switching, typed "
        "HotelEvent topics on an in-process bus, the maximo aconex/procore/bim "
        "out-of-scope refusal, and the donor's GRMS room-map evidence branch. "
        "Live mode is httpx and fails closed (refused) when the base URL is "
        "unconfigured. Fixture records vendored from the donor fixtures/."
    )
    layer = 3
    tags = ["connector", "hotel", "pms", "pos", "cmms", "event-bus", "hotelops"]
    requires = []

    default_config = {"fixture_mode": True}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "ingest", "system": "opera", "resource": "reservations"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self._bus = EventBus()
        self._settings = _ConnectorSettings(dict(self.config))
        self._connectors: Dict[str, BaseConnector] = {
            name: cls(self._settings, self._bus) for name, cls in CONNECTOR_CLASSES.items()
        }

    def _connector(self, system: str) -> BaseConnector:
        if system not in CONNECTOR_CLASSES:
            raise ConnectorError(f"unknown system: {system} (known: {sorted(CONNECTOR_CLASSES)})")
        return self._connectors[system]

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "ingest")).lower()
        try:
            if action == "systems":
                return _envelope("ok", {"systems": sorted(CONNECTOR_CLASSES)})
            if action == "connect":
                system = str(payload.get("system", "")).lower()
                return _envelope("ok", self._connector(system).connect())
            if action == "fetch":
                system = str(payload.get("system", "")).lower()
                resource = str(payload.get("resource", ""))
                if not resource:
                    return _envelope("refused", error="resource is required", detail={"action": action})
                data = self._connector(system).fetch(resource, id=payload.get("id"))
                return _envelope("ok", {"system": system, "resource": resource, "data": data})
            if action == "normalise":
                system = str(payload.get("system", "")).lower()
                resource = str(payload.get("resource", ""))
                raw = payload.get("raw")
                if not resource:
                    return _envelope("refused", error="resource is required", detail={"action": action})
                if raw is None:
                    return _envelope("refused", error="raw is required", detail={"action": action})
                events = self._connector(system).normalise(resource, raw)
                return _envelope("ok", {"events": [e.as_dict() for e in events], "count": len(events)})
            if action == "ingest":
                system = str(payload.get("system", "")).lower()
                resource = str(payload.get("resource", ""))
                if not resource:
                    return _envelope("refused", error="resource is required", detail={"action": action})
                result = self._connector(system).ingest(resource, id=payload.get("id"))
                return _envelope("ok", result)
            if action == "bus":
                return _envelope("ok", {
                    "events": self._bus.history(
                        surface=payload.get("surface"),
                        topic_prefix=payload.get("topic_prefix"),
                        limit=int(payload.get("limit", 200)),
                    )
                })
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["systems", "connect", "fetch", "normalise", "ingest", "bus"]})
        except (ConnectorError, GuardError) as exc:
            code = getattr(exc, "code", None) or "connector_error"
            return _envelope("refused", error=code, detail={"message": str(exc), "action": action})
        except httpx.HTTPError as exc:
            return _envelope("refused", error="live_http_failed", detail={"message": str(exc), "action": action})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
