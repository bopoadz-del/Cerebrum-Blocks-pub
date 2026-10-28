"""PPM + Licensing Compliance Resolver â€” refuse-by-design statutory floor,
ported from <private-repo> ``reasoning/ppm_resolver.py`` +
``reasoning/licensing.py`` + ``reasoning/market_router.py`` +
``reasoning/guard.py``.

Ported exactly:
- guard_request(): UAE + generic only. KSA and every other market are
  refused; Aconex/Procore/BIM source systems are refused.
- MarketRouter.normalize/licensing_pack/ppm_pack over the domain-kit JSON
  (licensing/uae/{licenses,prerequisite_map}.json,
  licensing/generic_template.json, ppm/uae_statutory.json) vendored inline
  in place of domain_kit.loader().
- PPMResolver.resolve(): a generic frequency table that claims to be
  authoritative is refused; an unnamed operator SOP is refused
  ('Frequencies are never estimated from the sheet.'); UAE assets outside
  the statutory floor are refused.
- LicensingEngine.evaluate(): three-valued fold (FAIL > UNPROVABLE > PASS,
  from reasoning/evidence.py combine_verdicts) over the real prerequisite
  graph; the master pacer is the unfinished fire/CD row, else the blocking
  licence with the most missing prerequisites. Computed, never looked up.
- Class B evidence metadata (reasoning/sheet.py class_b_meta) on every
  emitted work order and evaluation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "ppm_licensing_resolver", "status": status, "result": result, "error": error, "detail": detail}


# ---------------------------------------------------------------- sheet.py

SHEET_ID = "domain_encoding_sheet_sep2026"
CAVEAT = (
    "UNVERIFIED Class B (expert recall from Domain Encoding Sheet, Sep 2026). "
    "Do not treat sheet numbers or timings as Class A. Promote only when the "
    "owner uploads brand standards, manning, OS&E matrices, licence trackers, or PPM records."
)


def class_b_meta(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = {
        "evidence_class": "B",
        "source": SHEET_ID,
        "document_status": "UNVERIFIED",
        "caveat": CAVEAT,
    }
    if extra:
        payload.update(extra)
    return payload


# ---------------------------------------------------------------- evidence.py (fold)

class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNPROVABLE = "UNPROVABLE"


def combine_verdicts(verdicts: Iterable[Verdict]) -> Verdict:
    """FAIL beats UNPROVABLE beats PASS (conservative three-valued fold)."""
    values = list(verdicts)
    if any(v is Verdict.FAIL for v in values):
        return Verdict.FAIL
    if any(v is Verdict.UNPROVABLE for v in values):
        return Verdict.UNPROVABLE
    if values and all(v is Verdict.PASS for v in values):
        return Verdict.PASS
    return Verdict.UNPROVABLE


# ---------------------------------------------------------------- guard.py

# Market scope is data, not code: app/knowledge/ppm_markets.json carries the
# market sets together with their source record.
MARKETS_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "ppm_markets.json"


def load_markets(path: Optional[Path] = None) -> Tuple[set, set, Dict[str, Any]]:
    """Return (demo markets, unsupported markets, source record)."""
    path = Path(path) if path else MARKETS_PATH
    doc = json.loads(path.read_text(encoding="utf-8"))
    source = doc.get("source")
    if not isinstance(source, dict) or not source.get("origin"):
        raise ValueError(f"{path}: market sets carry no source record")
    sets = []
    for key in ("demo_markets", "unsupported_markets"):
        value = doc.get(key, [])
        if not isinstance(value, list):
            raise ValueError(f"{path}: {key} must be a list of market codes, got {type(value).__name__}")
        codes = set()
        for m in value:
            if not isinstance(m, str) or not m.strip():
                raise ValueError(f"{path}: {key} holds a blank or non-string market code: {m!r}")
            codes.add(m.strip().lower())
        sets.append(codes)
    demo, unsupported = sets
    if not demo:
        raise ValueError(f"{path}: no demo markets declared")
    if demo & unsupported:
        raise ValueError(f"{path}: markets both demo and unsupported: {sorted(demo & unsupported)}")
    return demo, unsupported, {**source, "path": str(path)}


DEMO_MARKETS, UNSUPPORTED_MARKETS, MARKETS_SOURCE = load_markets()
SUPPORTED_MARKETS = DEMO_MARKETS
FORBIDDEN_SOURCES = {"aconex", "procore", "bim", "bim_ifc", "navisworks", "revit"}


class GuardError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> Dict[str, Any]:
        return {"refused": True, "code": self.code, "message": self.message}


def guard_request(
    *,
    market: Optional[str] = None,
    source_system: Optional[str] = None,
    asset_sources: Optional[Iterable[str]] = None,
    construction_pm: bool = False,
    demo_only: bool = False,
    markets_path: Optional[Path] = None,
) -> None:
    if market:
        if markets_path:
            demo, unsupported, _ = load_markets(markets_path)
        else:
            demo, unsupported = DEMO_MARKETS, UNSUPPORTED_MARKETS
        code = market.lower()
        if code in unsupported:
            raise GuardError(
                "market_unsupported",
                "KSA is unsupported and stripped. Supported markets: UAE and generic only.",
            )
        if demo_only and code not in demo:
            raise GuardError(
                "market_not_demo_geography",
                "Pilot demo fixtures are UAE + generic only.",
            )
        if code not in demo:
            raise GuardError(
                "market_unsupported",
                "Supported markets: UAE and generic only.",
            )
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


# ---------------------------------------------------------------- domain data (domain_kit/licensing, ppm)

LICENSING_UAE: Dict[str, Any] = {
    "market": "uae",
    "licenses": [
        {"id": "UAE-DED", "name": "DED / DET trade license (hotel activity)", "authority": "DED_or_DET", "emirate": "all", "prerequisites": []},
        {"id": "UAE-EJARI", "name": "Ejari / tenancy registration (Dubai) or Tawtheeq (Abu Dhabi)", "authority": "rera_or_adrec", "prerequisites": ["UAE-DED"]},
        {"id": "UAE-UTIL", "name": "Utility accounts (DEWA / ADDC / SEWA + district cooling)", "authority": "utility", "prerequisites": ["UAE-DED", "UAE-EJARI"], "class_b_note": "Meters and account numbers are required before Civil Defense inspection pacing."},
        {"id": "UAE-ISP", "name": "Etisalat / du primary + failover circuits", "authority": "telecom", "prerequisites": ["UAE-DED"], "lead_time_days": 60, "class_b_note": "ISP lead time is a recurring M12 blocker; order at M02/M03, not at cutover."},
        {"id": "UAE-CCTV", "name": "Police-linked CCTV and control-room approval", "authority": "police", "prerequisites": ["UAE-DED"], "class_b_note": "Public-area and fire-command-room coverage is a commonly missed Civil Defense / occupancy prerequisite."},
        {"id": "UAE-CD", "name": "Civil Defense fire NOC", "authority": "civil_defense", "prerequisites": ["UAE-DED", "UAE-UTIL", "UAE-CCTV", "fire_pump_class_a", "fire_alarm_cx", "emergency_lighting_cx"]},
        {"id": "UAE-DTCM", "name": "DTCM hotel classification (Dubai) / DCT (Abu Dhabi)", "authority": "DTCM_or_DCT", "prerequisites": ["UAE-DED", "UAE-CD", "UAE-ISP"], "class_b_note": "Star classification inspects guest Wi-Fi, rooms, and public areas after fire NOC."},
        {"id": "UAE-DM-FOOD", "name": "Municipality food establishment permit", "authority": "DM_or_ADFCA", "prerequisites": ["UAE-DED"]},
        {"id": "UAE-POOL", "name": "Swimming pool / spa permit", "authority": "municipality_health", "prerequisites": ["UAE-DM-FOOD"]},
        {"id": "UAE-ESTAB", "name": "Establishment immigration card", "authority": "ICP_or_GDRFA", "prerequisites": ["UAE-DED"]},
        {"id": "UAE-MUSIC", "name": "Music / public performance", "authority": "copyright_society_uae", "prerequisites": ["UAE-DTCM"], "optional": True},
        {"id": "UAE-SIGNAGE", "name": "External signage permit", "authority": "municipality", "prerequisites": ["UAE-DED"], "optional": True},
    ],
}

PREREQ_UAE: Dict[str, Any] = {
    "market": "uae",
    "maps": {
        "UAE-UTIL": ["UAE-DED", "UAE-EJARI"],
        "UAE-ISP": ["UAE-DED"],
        "UAE-CCTV": ["UAE-DED"],
        "UAE-CD": ["UAE-DED", "UAE-UTIL", "UAE-CCTV", "fire_pump_class_a", "fire_alarm_cx", "emergency_lighting_cx"],
        "UAE-DTCM": ["UAE-DED", "UAE-CD", "UAE-ISP"],
        "UAE-DM-FOOD": ["UAE-DED"],
        "UAE-POOL": ["UAE-DM-FOOD"],
        "UAE-ESTAB": ["UAE-DED"],
        "UAE-EJARI": ["UAE-DED"],
        "fire_pump_class_a": ["INV-FIRE-PUMP-COVERS-CLIPS:clear", "INV-FIRE-PUMP-SERIAL-MISMATCH:clear", "INV-FIRE-PUMP-STALE-TEST:clear"],
        "soft_opening": ["UAE-DED", "UAE-CD", "UAE-DTCM", "UAE-UTIL", "UAE-CCTV"],
    },
    "refuse": {
        "unsupported_market": "Pilot markets are UAE + generic only. No other country pack is loaded.",
        "missing_prereq": "License is UNPROVABLE until every prerequisite is PASS.",
    },
}

LICENSING_GENERIC: Dict[str, Any] = {
    "market": "generic",
    "licenses": [
        {"id": "GEN-TRADE", "name": "Trade / establishment license", "authority": "local_municipality", "prerequisites": []},
        {"id": "GEN-UTIL", "name": "Utility accounts (power, water, district cooling)", "authority": "utility_companies", "prerequisites": ["GEN-TRADE"], "class_b_note": "Account opening is a common critical-path miss; meters and contract numbers are required before fire occupancy inspection."},
        {"id": "GEN-ISP", "name": "Primary + failover ISP circuits", "authority": "telecom", "prerequisites": ["GEN-TRADE"], "lead_time_days": 60, "class_b_note": "Circuit lead time regularly exceeds FF&E install. Order at design freeze, not at systems cutover."},
        {"id": "GEN-CCTV", "name": "CCTV / security control-room permit", "authority": "police_or_municipality", "prerequisites": ["GEN-TRADE"], "class_b_note": "Camera coverage of public areas and the fire command room is a commonly missed occupancy prerequisite."},
        {"id": "GEN-FIRE", "name": "Fire safety occupancy", "authority": "fire_service", "prerequisites": ["GEN-TRADE", "GEN-UTIL", "GEN-CCTV", "fire_pump_class_a_or_b"]},
        {"id": "GEN-FOOD", "name": "Food premises permit", "authority": "health", "prerequisites": ["GEN-TRADE"]},
        {"id": "GEN-TOURISM", "name": "Tourism / lodging permit", "authority": "tourism_board", "prerequisites": ["GEN-TRADE", "GEN-FIRE"]},
        {"id": "GEN-STAR", "name": "Star / classification inspection", "authority": "tourism_board", "prerequisites": ["GEN-TOURISM", "GEN-ISP"], "class_b_note": "Classification inspects rooms, public areas, and guest Wi-Fi. Incomplete ISP or model rooms block the star rating, not just the trade license."},
        {"id": "GEN-POOL", "name": "Pool / spa health", "authority": "health", "prerequisites": ["GEN-FOOD"], "optional": True},
        {"id": "GEN-MUSIC", "name": "Public performance / music", "authority": "copyright_society", "prerequisites": ["GEN-TRADE"], "optional": True},
    ],
    "prerequisite_map": {
        "GEN-FIRE": ["GEN-TRADE", "GEN-UTIL", "GEN-CCTV", "fire_pump_class_a_or_b"],
        "GEN-TOURISM": ["GEN-TRADE", "GEN-FIRE"],
        "GEN-STAR": ["GEN-TOURISM", "GEN-ISP"],
        "soft_opening": ["GEN-TRADE", "GEN-FIRE", "GEN-TOURISM"],
    },
}

PPM_UAE: Dict[str, Any] = {
    "layer": "statutory_floor",
    "market": "uae",
    "authoritative_frequencies": False,
    "never_estimate": True,
    "note": "Jurisdiction floor only: fire, lift, pressure vessel, water hygiene. Frequencies are NOT estimated here. Refer to the named statute text and the operator SOP layer.",
    "duties": [
        {"id": "STAT-FIRE", "asset_types": ["fire_pump", "fire_alarm", "emergency_lighting", "kitchen_hood"], "authority": "civil_defense", "legacy_task_id": "PPM-CD-FIRE-PUMP"},
        {"id": "STAT-LIFT", "asset_types": ["elevator"], "authority": "emirates_authority", "legacy_task_id": "PPM-LIFT"},
        {"id": "STAT-PRESSURE", "asset_types": ["pressure_vessel", "generator"], "authority": "civil_defense_and_operator", "legacy_task_id": "PPM-GENSET"},
        {"id": "STAT-WATER", "asset_types": ["domestic_water", "backflow_preventer"], "authority": "municipality_health", "legacy_task_id": "PPM-LEGIONELLA"},
    ],
    "tasks": [
        {"id": "PPM-CD-FIRE-PUMP", "asset_type": "fire_pump", "authority": "civil_defense", "require_sop": True, "require_witness": True, "cadence_authoritative": False, "statutory_duty": "STAT-FIRE"},
        {"id": "PPM-CD-ALARM", "asset_type": "fire_alarm", "authority": "civil_defense", "require_sop": True, "cadence_authoritative": False, "statutory_duty": "STAT-FIRE"},
        {"id": "PPM-CD-ELIGHT", "asset_type": "emergency_lighting", "authority": "civil_defense", "require_sop": True, "cadence_authoritative": False, "statutory_duty": "STAT-FIRE"},
        {"id": "PPM-LIFT", "asset_type": "elevator", "authority": "emirates_authority", "require_sop": True, "cadence_authoritative": False, "statutory_duty": "STAT-LIFT"},
        {"id": "PPM-HOOD", "asset_type": "kitchen_hood", "authority": "civil_defense", "require_sop": True, "cadence_authoritative": False, "statutory_duty": "STAT-FIRE"},
        {"id": "PPM-LEGIONELLA", "asset_type": "domestic_water", "authority": "municipality_health", "require_sop": True, "cadence_authoritative": False, "statutory_duty": "STAT-WATER"},
        {"id": "PPM-BACKFLOW", "asset_type": "backflow_preventer", "authority": "dewa_or_adwea", "require_sop": True, "cadence_authoritative": False, "statutory_duty": "STAT-WATER"},
        {"id": "PPM-GENSET", "asset_type": "generator", "authority": "civil_defense", "require_sop": True, "cadence_authoritative": False, "statutory_duty": "STAT-PRESSURE"},
    ],
    **class_b_meta(),
}


# ---------------------------------------------------------------- market_router.py

class MarketRouter:
    DEMO = {"uae", "generic"}

    def normalize(self, market: Optional[str], *, demo_only: bool = False) -> str:
        code = (market or "generic").lower().strip()
        guard_request(market=code, demo_only=demo_only)
        if code in {"dubai", "abu_dhabi", "abudhabi", "sharjah", "ajman", "uae"}:
            return "uae"
        if code == "generic":
            return "generic"
        raise GuardError("market_unsupported", f"Market {market!r} is not UAE or generic.")

    def licensing_pack(self, market: Optional[str]) -> Dict[str, Any]:
        code = self.normalize(market)
        if code == "uae":
            return {
                "market": "uae",
                "licenses": LICENSING_UAE["licenses"],
                "prerequisites": PREREQ_UAE["maps"],
                **class_b_meta(),
            }
        return {
            "market": "generic",
            "licenses": LICENSING_GENERIC["licenses"],
            "prerequisites": LICENSING_GENERIC.get("prerequisite_map") or {},
            **class_b_meta(),
        }

    def ppm_pack(self, market: Optional[str]) -> Dict[str, Any]:
        code = self.normalize(market)
        if code == "uae":
            return PPM_UAE
        return {
            "market": code,
            "layer": "statutory_floor",
            "authoritative_frequencies": False,
            "tasks": [],
            "duties": [
                {"id": "STAT-FIRE", "asset_types": ["fire_pump", "fire_alarm"], "authority": "fire_service"},
                {"id": "STAT-LIFT", "asset_types": ["elevator"], "authority": "lift_authority"},
                {"id": "STAT-PRESSURE", "asset_types": ["pressure_vessel"], "authority": "pressure_vessel"},
                {"id": "STAT-WATER", "asset_types": ["domestic_water"], "authority": "water_hygiene"},
            ],
            "note": "Statutory floor only. Operator SOP is mandatory. Frequencies are never estimated.",
            **class_b_meta(),
        }


# ---------------------------------------------------------------- ppm_resolver.py

class PPMRefuse(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> Dict[str, Any]:
        return {"refused": True, "code": self.code, "message": self.message, **class_b_meta()}


@dataclass
class PPMWorkOrder:
    task_id: str
    asset_type: str
    market: str
    sop_present: bool
    authority: str
    statutory_duty: Optional[str] = None
    cadence_days: Optional[int] = None
    cadence_authoritative: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "asset_type": self.asset_type,
            "cadence_days": self.cadence_days,
            "cadence_authoritative": False,
            "cadence_note": "Frequency is not estimated. Refer to the named operator SOP and the statute.",
            "market": self.market,
            "sop_present": self.sop_present,
            "authority": self.authority,
            "statutory_duty": self.statutory_duty,
            "status": "issued",
            **class_b_meta(),
        }


class PPMResolver:
    def __init__(self) -> None:
        self.router = MarketRouter()

    def _duty_for(self, pack: Dict[str, Any], asset_type: str) -> Optional[Dict[str, Any]]:
        for duty in pack.get("duties") or []:
            if asset_type in (duty.get("asset_types") or []):
                return duty
        return None

    def resolve(
        self,
        *,
        market: str,
        asset_type: str,
        operator_sop: Optional[str],
        task_id: Optional[str] = None,
    ) -> PPMWorkOrder:
        pack = self.router.ppm_pack(market)
        code = self.router.normalize(market)
        if pack.get("authoritative_frequencies"):
            raise PPMRefuse(
                "generic_frequency_refused",
                "A generic frequency table cannot be treated as authoritative.",
            )

        tasks = pack.get("tasks") or []
        match = None
        for row in tasks:
            if task_id and row["id"] == task_id:
                match = row
                break
            if row.get("asset_type") == asset_type:
                match = row
                break
        duty = self._duty_for(pack, asset_type)

        if match is None and duty is None and code == "uae":
            raise PPMRefuse(
                "statutory_missing",
                f"No statutory-floor duty for asset_type={asset_type!r} in UAE (fire/lift/pressure/water).",
            )

        named = operator_sop and operator_sop.strip() and len(operator_sop.strip()) > 8
        if not named:
            raise PPMRefuse(
                "sop_missing",
                "Named operator SOP is required. See domain_kit/ppm/operator_sop/README.md. "
                "Frequencies are never estimated from the sheet.",
            )

        if match:
            return PPMWorkOrder(
                task_id=match["id"],
                asset_type=match.get("asset_type", asset_type),
                market=code,
                sop_present=True,
                authority=match.get("authority", "operator_sop"),
                statutory_duty=match.get("statutory_duty") or (duty or {}).get("id"),
            )
        return PPMWorkOrder(
            task_id=task_id or (duty or {}).get("legacy_task_id") or f"PPM-{asset_type.upper()}",
            asset_type=asset_type,
            market=code,
            sop_present=True,
            authority=(duty or {}).get("authority", "operator_sop"),
            statutory_duty=(duty or {}).get("id"),
        )


# ---------------------------------------------------------------- licensing.py

class LicensingEngine:
    def __init__(self) -> None:
        self.router = MarketRouter()

    def evaluate(self, market: str, satisfied: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """`satisfied` maps license/prereq id -> PASS|FAIL|UNPROVABLE."""
        pack = self.router.licensing_pack(market)
        satisfied = {k: v.upper() for k, v in (satisfied or {}).items()}
        results: List[Dict[str, Any]] = []
        mapped = pack.get("prerequisites") or {}
        for lic in pack["licenses"]:
            prereqs = list(lic.get("prerequisites") or [])
            extra = mapped.get(lic["id"], [])
            needed = list(dict.fromkeys(prereqs + extra))
            prereq_verdicts = []
            missing = []
            for item in needed:
                raw = satisfied.get(item)
                if raw is None:
                    prereq_verdicts.append(Verdict.UNPROVABLE)
                    missing.append(item)
                else:
                    prereq_verdicts.append(Verdict(raw))
            if lic["id"] in satisfied:
                own = Verdict(satisfied[lic["id"]])
            elif not needed:
                own = Verdict.UNPROVABLE
            else:
                own = combine_verdicts(prereq_verdicts)
            results.append(
                {
                    "id": lic["id"],
                    "name": lic["name"],
                    "verdict": own.value,
                    "missing_prerequisites": missing,
                    "optional": bool(lic.get("optional")),
                }
            )
        blocking = [r for r in results if r["verdict"] != "PASS" and not r["optional"]]
        overall = combine_verdicts(Verdict(r["verdict"]) for r in results if not r["optional"])
        fire_ids = {"UAE-CD", "GEN-FIRE"}
        fire_rows = [r for r in results if r["id"] in fire_ids]
        pacer = None
        if fire_rows and fire_rows[0]["verdict"] != "PASS":
            pacer = fire_rows[0]["id"]
        elif blocking:
            pacer = max(blocking, key=lambda r: len(r["missing_prerequisites"]))["id"]
        return {
            "market": pack["market"],
            "overall": overall.value,
            "licenses": results,
            "soft_opening_blocked": any(
                r["id"] in {"UAE-CD", "UAE-DTCM", "GEN-FIRE", "GEN-TOURISM"}
                and r["verdict"] != "PASS"
                for r in results
            ),
            "blocking": blocking,
            "master_pacer": {
                "license_id": pacer,
                "kind": "fire_cd" if pacer in fire_ids else "licensing_path",
                "method": "computed_from_prerequisite_graph",
                **class_b_meta(),
            },
            **class_b_meta(),
        }


class PpmLicensingResolverBlock(UniversalBlock):
    """Refuse-by-design PPM/licensing resolver ported from <private-repo>."""

    name = "ppm_licensing_resolver"
    version = "1.0.0"
    description = (
        "PPM + licensing compliance resolver ported from <private-repo> "
        "reasoning/ppm_resolver.py + licensing.py + market_router.py + guard.py: "
        "UAE + generic only (KSA refused), Aconex/Procore/BIM sources refused, "
        "generic frequency tables refused as authority, unnamed operator SOP "
        "refused (frequencies are never estimated from the sheet), and a "
        "three-valued FAIL > UNPROVABLE > PASS fold over the real prerequisite "
        "graph with a computed master pacer. Real; domain data vendored from "
        "the donor's domain_kit licensing/ppm JSON (Class B evidence metadata)."
    )
    layer = 3
    tags = ["hotel", "compliance", "ppm", "licensing", "refuse-by-design", "hotelops"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "resolve_ppm", "market": "uae", "asset_type": "fire_pump", "operator_sop": "Operator ABC SOP v3"}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def __init__(self, hal_block=None, config: Dict[str, Any] = None):
        super().__init__(hal_block=hal_block, config=config)
        self.router = MarketRouter()
        self.ppm = PPMResolver()
        self.licensing = LicensingEngine()

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "resolve_ppm")).lower()
        try:
            if action == "resolve_ppm":
                if not payload.get("market"):
                    return _envelope("refused", error="market is required", detail={"action": action})
                if not payload.get("asset_type"):
                    return _envelope("refused", error="asset_type is required", detail={"action": action})
                order = self.ppm.resolve(
                    market=str(payload["market"]),
                    asset_type=str(payload["asset_type"]),
                    operator_sop=payload.get("operator_sop"),
                    task_id=payload.get("task_id"),
                )
                return _envelope("ok", order.as_dict())
            if action == "evaluate_licensing":
                if not payload.get("market"):
                    return _envelope("refused", error="market is required", detail={"action": action})
                satisfied = payload.get("satisfied")
                if satisfied is not None and not isinstance(satisfied, dict):
                    return _envelope("refused", error="satisfied must be a dict of id -> PASS|FAIL|UNPROVABLE", detail={"action": action})
                return _envelope("ok", self.licensing.evaluate(str(payload["market"]), satisfied))
            if action == "guard":
                guard_request(
                    market=payload.get("market"),
                    source_system=payload.get("source_system"),
                    asset_sources=payload.get("asset_sources"),
                    construction_pm=bool(payload.get("construction_pm", False)),
                    demo_only=bool(payload.get("demo_only", False)),
                )
                return _envelope("ok", {"guarded": True, "market": payload.get("market"), "source_system": payload.get("source_system")})
            if action == "normalize_market":
                return _envelope("ok", {"code": self.router.normalize(payload.get("market"), demo_only=bool(payload.get("demo_only", False)))})
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["resolve_ppm", "evaluate_licensing", "guard", "normalize_market"]})
        except (PPMRefuse, GuardError) as exc:
            return _envelope("refused", result=exc.as_dict(), error=exc.code, detail={"action": action})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
