"""DEXPI Ingest — namespace-tolerant DEXPI/Proteus XML parser, ported from
<private-repo> ``src/<private-repo>/ingest_dexpi.py``.

Ported: the supported element families (Sheet/Drawing, Equipment, Nozzle,
Pipeline/Line + Component children, Instrument, BatteryLimit, DesignVolume,
System) with attribute-tolerant extraction into a normalized entity list.
WALLS carried from the donor: full DEXPI XSD certification, Proteus schema
namespaces, component catalogues and vendor extensions are NOT implemented.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "dexpi_ingest", "status": status, "result": result, "error": error, "detail": detail}


def _local(el: ET.Element) -> str:
    tag = el.tag
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _text(el: Optional[ET.Element], default: str = "") -> str:
    if el is None or el.text is None:
        return default
    return el.text.strip()


def _attr(el: ET.Element, *names: str) -> str:
    for name in names:
        val = el.attrib.get(name)
        if val not in (None, ""):
            return val
    return ""


def parse_dexpi(xml_text: str) -> Dict[str, Any]:
    root = ET.fromstring(xml_text)
    entities: List[Dict[str, Any]] = []
    family_map = {
        "Equipment": "equipment",
        "ProcessEquipment": "equipment",
        "Nozzle": "nozzle",
        "PipingNetworkSegment": "pipeline",
        "PipeLine": "pipeline",
        "Line": "pipeline",
        "Instrument": "instrument",
        "InstrumentationFunction": "instrument",
        "ProcessInstrument": "instrument",
        "BatteryLimit": "battery_limit",
        "PlantAreaBoundary": "battery_limit",
        "DesignVolume": "design_volume",
        "Volume": "design_volume",
        "System": "system",
        "Sheet": "sheet",
        "Drawing": "sheet",
    }
    for el in root.iter():
        local = _local(el)
        family = family_map.get(local)
        if family is None:
            continue
        entity = {
            "family": family,
            "tag": _attr(el, "TagName", "Name", "ID"),
            "name": _text(el)[:200] if _text(el) else _attr(el, "TagName", "Name", "ID"),
            "attributes": {k: v for k, v in el.attrib.items()},
        }
        if family == "pipeline":
            comps = []
            for child in el:
                if _local(child) in ("Component", "PipingComponent"):
                    comps.append({"tag": _attr(child, "TagName", "Name", "ID")})
            entity["components"] = comps
        entities.append(entity)
    return {"entities": entities, "count": len(entities), "families": sorted({e["family"] for e in entities})}


class DexpiIngestBlock(UniversalBlock):
    """DEXPI/Proteus XML parser ported from <private-repo>."""

    name = "dexpi_ingest"
    version = "1.0.0"
    description = (
        "DEXPI/Proteus XML parser ported from <private-repo> ingest_dexpi.py: "
        "namespace-tolerant extraction of Sheet/Drawing, Equipment, Nozzle, "
        "Pipeline (+Component children), Instrument, BatteryLimit, DesignVolume "
        "and System into a normalized entity list. WALLS carried: full DEXPI XSD "
        "certification, Proteus schema namespaces and vendor extensions are NOT "
        "implemented."
    )
    layer = 3
    tags = ["dexpi", "xml", "piping", "<private-repo>", "digital-thread"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "parse", "xml": "<PlantModel><Equipment TagName=\\"P-101\\"/></PlantModel>"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "parse")).lower()
        try:
            if action == "parse":
                xml_text = str(payload.get("xml", ""))
                if not xml_text.strip():
                    return _envelope("error", error="xml is required")
                return _envelope("ok", parse_dexpi(xml_text))
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["parse"]})
        except ET.ParseError as exc:
            return _envelope("error", error=f"malformed XML: {exc}", detail={"type": "ParseError"})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
