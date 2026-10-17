"""Aviation Block v2 - TypedBlock implementation

This is the v2 implementation that:
- Extends TypedBlock instead of UniversalContainer
- Accepts TextContent input (from pdf_v2, ocr_v2, etc.)
- Outputs AviationAnalysis type
- Has a single process() entry point instead of action routing
- Internal methods are private (_ prefixed)
- Uses deterministic regex + math, no LLM calls, no external APIs
"""

import re
from typing import Any, Dict, List, Optional

from app.core.domain_block_v2 import DomainBlockV2
from app.core.schema_registry import TextContent, AviationAnalysis
from app.core.aviation_types import RiskScore

from app.core.aviation_knowledge import AviationKnowledge, COMPLIANCE_KEYWORDS
from app.core.http_errors import error_kind

_rk = AviationKnowledge()


class AviationBlockV2(DomainBlockV2):
    """
    Aviation Block v2 - TypedBlock implementation for aviation document analysis.

    Input: TextContent (extracted document text)
    Output: AviationAnalysis (entities, metrics, compliance flags, risk scores)
    """

    name = "aviation_v2"
    version = "2.0"
    description = "Aviation document analysis with typed input/output"
    layer = 3
    tags = ["domain", "aviation", "v2"]
    requires = []

    default_config = {
        "confidence_threshold": 0.85,
    }

    input_schema = TextContent
    output_schema = AviationAnalysis

    accepted_input_types = ["TextContent", "PDFContent"]
    produced_output_types = ["AviationAnalysis"]

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste aviation document text...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "utilization_rate", "type": "number", "label": "Utilization %"},
                {"name": "dispatch_reliability", "type": "number", "label": "Dispatch Reliability %"},
                {"name": "on_time_performance", "type": "number", "label": "OTP %"},
                {"name": "fuel_burn_per_hour", "type": "number", "label": "Fuel Burn / hr"},
                {"name": "airworthiness_risk", "type": "number", "label": "Airworthiness Risk"},
                {"name": "operational_risk", "type": "number", "label": "Operational Risk"},
                {"name": "maintenance_risk", "type": "number", "label": "Maintenance Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📄", "label": "Analyze Maintenance Log", "prompt": "Analyze this maintenance log"},
            {"icon": "✈️", "label": "Check EASA Compliance", "prompt": "Check this document for EASA compliance"},
            {"icon": "⚠️", "label": "Score Aviation Risks", "prompt": "Score aviation risks for this document"},
            {"icon": "🔍", "label": "Extract Aircraft & Hours", "prompt": "Extract aircraft and hours from this document"},
        ],
    }

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """Main entry point - analyze aviation document text."""
        params = params or {}

        text = self._extract_text(input_data)
        if not text:
            return self._empty_analysis("No text provided")

        custom_rules = params.get("custom_rules") or params.get("rules")
        if custom_rules:
            _rk.set_custom_rules(custom_rules)

        document_type = params.get("document_type") or params.get("analysis_type") or self._detect_document_type(text)

        if document_type == "maintenance_log":
            return await self._analyze_maintenance_log(text, params)
        if document_type == "flight_manual":
            return await self._analyze_flight_manual(text, params)
        if document_type == "minimum_equipment_list":
            return await self._analyze_minimum_equipment_list(text, params)
        if document_type == "incident_report":
            return await self._analyze_incident_report(text, params)
        if document_type == "training_record":
            return await self._analyze_training_record(text, params)
        if document_type == "dispatch_release":
            return await self._analyze_dispatch_release(text, params)
        if document_type == "lease_agreement":
            return await self._analyze_lease_agreement(text, params)
        if document_type == "airworthiness_directive":
            return await self._analyze_airworthiness_directive(text, params)

        return await self._analyze_generic(text, params)

    # ------------------------------------------------------------------
    # TEXT EXTRACTION
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DOCUMENT TYPE DETECTION
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        """Auto-detect aviation document type from content."""
        text_lower = text[:5000].lower()

        if any(kw in text_lower for kw in ['maintenance', 'check', 'inspection', 'ad', 'sb', 'component', 'tsn', 'tso', 'overhaul']):
            return "maintenance_log"
        if any(kw in text_lower for kw in ['afm', 'poh', 'limitation', 'performance', 'weight and balance', 'v-speed', 'emergency procedure']):
            return "flight_manual"
        if any(kw in text_lower for kw in ['mel', 'cdl', 'inoperative', 'placard', 'dispatch condition', 'repair interval']):
            return "minimum_equipment_list"
        if any(kw in text_lower for kw in ['incident', 'accident', 'ntsb', 'occurrence', 'asrs', 'safety report', 'near miss']):
            return "incident_report"
        if any(kw in text_lower for kw in ['training', 'certificate', 'type rating', 'recurrent', 'sim', 'lpc', 'opc', 'check ride']):
            return "training_record"
        if any(kw in text_lower for kw in ['dispatch', 'flight plan', 'weather', 'notam', 'fuel', 'alternate', 'etops', 'mel item']):
            return "dispatch_release"
        if any(kw in text_lower for kw in ['dry lease', 'wet lease', 'acmi', 'lease rate', 'redelivery', 'maintenance reserve', 'utilization']):
            return "lease_agreement"
        if any(kw in text_lower for kw in ['ad', 'airworthiness directive', 'compliance', 'repetitive inspection', 'terminating action']):
            return "airworthiness_directive"

        return "generic"

    # ------------------------------------------------------------------
    # ANALYSIS METHODS (private)
    # ------------------------------------------------------------------

    async def _analyze_maintenance_log(self, text: str, params: Dict) -> Dict:
        """Analyze maintenance log text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "maintenance_log"
        return self._finalize_result(result, params)

    async def _analyze_flight_manual(self, text: str, params: Dict) -> Dict:
        """Analyze flight manual text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "flight_manual"
        return self._finalize_result(result, params)

    async def _analyze_minimum_equipment_list(self, text: str, params: Dict) -> Dict:
        """Analyze minimum equipment list text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "minimum_equipment_list"
        return self._finalize_result(result, params)

    async def _analyze_incident_report(self, text: str, params: Dict) -> Dict:
        """Analyze incident report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "incident_report"
        return self._finalize_result(result, params)

    async def _analyze_training_record(self, text: str, params: Dict) -> Dict:
        """Analyze training record text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "training_record"
        return self._finalize_result(result, params)

    async def _analyze_dispatch_release(self, text: str, params: Dict) -> Dict:
        """Analyze dispatch release text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "dispatch_release"
        return self._finalize_result(result, params)

    async def _analyze_lease_agreement(self, text: str, params: Dict) -> Dict:
        """Analyze lease agreement text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "lease_agreement"
        return self._finalize_result(result, params)

    async def _analyze_airworthiness_directive(self, text: str, params: Dict) -> Dict:
        """Analyze airworthiness directive text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "airworthiness_directive"
        return self._finalize_result(result, params)

    async def _analyze_generic(self, text: str, params: Dict) -> Dict:
        """Generic analysis for unknown document types."""
        result = self._build_analysis(text, params)
        result["document_type"] = "generic"
        return self._finalize_result(result, params)

    # ------------------------------------------------------------------
    # BUILDERS
    # ------------------------------------------------------------------

    def _build_analysis(self, text: str, params: Dict) -> Dict:
        """Run all extraction passes and return a working dict."""
        entities = {
            "aircraft_registrations": self._extract_aircraft_registrations(text),
            "serial_numbers": self._extract_serial_numbers(text),
            "engine_models": self._extract_engine_models(text),
            "part_numbers": self._extract_part_numbers(text),
            "flight_hours": self._extract_flight_hours(text),
            "airports": self._extract_airports(text),
            "crew_names": self._extract_crew_names(text),
            "operators": self._extract_operators(text),
        }
        metrics = {
            "utilization_rate": self._extract_utilization_rate(**params.get("utilization_rate", {})),
            "dispatch_reliability": self._extract_dispatch_reliability(**params.get("dispatch_reliability", {})),
            "on_time_performance": self._extract_on_time_performance(**params.get("on_time_performance", {})),
            "mtbf": self._extract_mtbf(**params.get("mtbf", {})),
            "mttr": self._extract_mttr(**params.get("mttr", {})),
            "fuel_burn_per_hour": self._extract_fuel_burn_per_hour(**params.get("fuel_burn_per_hour", {})),
            "payload_utilization": self._extract_payload_utilization(**params.get("payload_utilization", {})),
            "lease_rate_factor": self._extract_lease_rate_factor(**params.get("lease_rate_factor", {})),
        }
        compliance_flags = {
            "easa": self._check_easa(text),
            "faa_part_121": self._check_faa_part_121(text),
            "icao_sms": self._check_icao_sms(text),
            "etops": self._check_etops(text),
            "carbon_offsetting": self._check_carbon_offsetting(text),
        }
        risk_scores = {
            "airworthiness_risk": self._score_airworthiness_risk(text),
            "operational_risk": self._score_operational_risk(text),
            "maintenance_risk": self._score_maintenance_risk(text),
            "financial_risk": self._score_financial_risk(text),
            "reputational_risk": self._score_reputational_risk(text),
            "overall_risk": self._compute_overall_risk(text),
        }
        custom_rule_hits = _rk.check_custom_rules(text)

        return {
            "document_type": "unknown",
            "entities": entities,
            "metrics": metrics,
            "financials": {},
            "compliance_flags": compliance_flags,
            "risk_scores": risk_scores,
            "custom_rule_hits": custom_rule_hits,
            "text": text,
            "raw_text": text[:2000] if params.get("include_raw") else "",
            "metadata": {
                "extracted_at": self._timestamp(),
                "entity_count": sum(len(v) for v in entities.values()),
                "metric_count": sum(1 for v in metrics.values() if v and v.get("value") not in (None, [], "")),
                "aircraft_type": self._extract_aircraft_type(text),
            },
        }

    def _extract_aircraft_type(self, text: str) -> Optional[str]:
        """Best-effort extraction of aircraft type."""
        pattern = r"(?:aircraft type|aircraft_type)[:\s]+([A-Z][A-Za-z0-9\s&.,-]{2,60})"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            return match.group(1).strip()
        return None

    # ------------------------------------------------------------------
    # ENTITY EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_aircraft_registrations(self, text: str) -> List[Dict]:
        """Extract aircraft registrations from text."""
        found = []
        for match in re.finditer(r"\b(N\d{1,5}[A-Z]{1,2}|[A-Z]-[A-Z]{4})\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "aircraft_registrations",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_serial_numbers(self, text: str) -> List[Dict]:
        """Extract serial numbers from text."""
        found = []
        for match in re.finditer(r"(?:msn|serial number|line number)\s*#?\s*(\d{4,6})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "serial_numbers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_engine_models(self, text: str) -> List[Dict]:
        """Extract engine models from text."""
        found = []
        for match in re.finditer(r"\b(CFM56|V2500|GE90|Trent|PW4000|CF6|LEAP|GEnx)\b", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "engine_models",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_part_numbers(self, text: str) -> List[Dict]:
        """Extract part numbers from text."""
        found = []
        for match in re.finditer(r"(?:part number|ipc reference|cmm reference)\s*#?\s*([A-Z0-9\-]{5,15})", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "part_numbers",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_flight_hours(self, text: str) -> List[Dict]:
        """Extract flight hours from text."""
        found = []
        for match in re.finditer(r"(\d{1,5}(?:\.\d+)?)\s*(flight hours|fh|cycles|landings)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "flight_hours",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_airports(self, text: str) -> List[Dict]:
        """Extract airports from text."""
        found = []
        # Airport codes are uppercase IATA/ICAO; require an explicit
        # airport-context keyword so prose words ("THE", "FORM") never
        # become airport entities (survey cluster finding).
        for match in re.finditer(r"\b([A-Z]{3,4})\b(?=\s+(?:airport|international))", text):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "airports",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_crew_names(self, text: str) -> List[Dict]:
        """Extract crew names from text."""
        found = []
        for match in re.finditer(r"(?:captain|first officer|pilot|flight engineer|cabin crew|mechanic)\s*[\-:]?\s*([A-Z][A-Za-z\s\.]+)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "crew_names",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    def _extract_operators(self, text: str) -> List[Dict]:
        """Extract operators from text."""
        found = []
        for match in re.finditer(r"(?:operator|airline|carrier|mro|lessor|owner)\s*[\-:]?\s*([A-Z][A-Za-z0-9\s&.,]+(?:Inc\.?|LLC|Ltd\.?|Corp\.?)?)", text, re.IGNORECASE):
            value = next((g for g in match.groups() if g is not None), None)
            if value:
                found.append({
                    "type": "operators",
                    "value": value.strip(),
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 20):match.end() + 20],
                })
        return self._deduplicate_entities(found)

    # ------------------------------------------------------------------
    # METRICS & FORMULA EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_utilization_rate(self, flight_hours=None, available_hours=None) -> Dict[str, Any]:
        """Calculate utilization rate."""
        try:
            value = self._safe_divide(flight_hours, available_hours, scale=100) if (flight_hours is not None and available_hours is not None) else None
            if value is None:
                return {"name": "utilization_rate", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "utilization_rate", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "utilization_rate", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_dispatch_reliability(self, dispatched_flights=None, scheduled_flights=None) -> Dict[str, Any]:
        """Calculate dispatch reliability."""
        try:
            value = self._safe_divide(dispatched_flights, scheduled_flights, scale=100) if (dispatched_flights is not None and scheduled_flights is not None) else None
            if value is None:
                return {"name": "dispatch_reliability", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "dispatch_reliability", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "dispatch_reliability", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_on_time_performance(self, on_time=None, total=None) -> Dict[str, Any]:
        """Calculate on time performance."""
        try:
            value = self._safe_divide(on_time, total, scale=100) if (on_time is not None and total is not None) else None
            if value is None:
                return {"name": "on_time_performance", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "on_time_performance", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "on_time_performance", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_mtbf(self, total_hours=None, failures=None) -> Dict[str, Any]:
        """Calculate mtbf."""
        try:
            value = self._safe_divide(total_hours, failures) if (total_hours is not None and failures is not None) else None
            if value is None:
                return {"name": "mtbf", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "mtbf", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "mtbf", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_mttr(self, total_repair_time=None, repairs=None) -> Dict[str, Any]:
        """Calculate mttr."""
        try:
            value = self._safe_divide(total_repair_time, repairs) if (total_repair_time is not None and repairs is not None) else None
            if value is None:
                return {"name": "mttr", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "mttr", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "mttr", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_fuel_burn_per_hour(self, total_fuel=None, flight_hours=None) -> Dict[str, Any]:
        """Calculate fuel burn per hour."""
        try:
            value = self._safe_divide(total_fuel, flight_hours) if (total_fuel is not None and flight_hours is not None) else None
            if value is None:
                return {"name": "fuel_burn_per_hour", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "fuel_burn_per_hour", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "fuel_burn_per_hour", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_payload_utilization(self, actual_payload=None, max_payload=None) -> Dict[str, Any]:
        """Calculate payload utilization."""
        try:
            value = self._safe_divide(actual_payload, max_payload, scale=100) if (actual_payload is not None and max_payload is not None) else None
            if value is None:
                return {"name": "payload_utilization", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "payload_utilization", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "payload_utilization", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    def _extract_lease_rate_factor(self, monthly_lease=None, aircraft_value=None) -> Dict[str, Any]:
        """Calculate lease rate factor."""
        try:
            value = self._safe_divide(monthly_lease, aircraft_value, scale=100) if (monthly_lease is not None and aircraft_value is not None) else None
            if value is None:
                return {"name": "lease_rate_factor", "value": None, "inputs": {}, "error": "Insufficient inputs"}
            return {"name": "lease_rate_factor", "value": round(value, 2), "inputs": {k: v for k, v in locals().items() if k not in ("value", "self")}, "confidence": 0.85}
        except Exception as e:
            return {"name": "lease_rate_factor", "value": None, "inputs": {}, "error": str(e), "error_kind": error_kind(e)}

    # ------------------------------------------------------------------
    # REGULATORY & COMPLIANCE CHECKING (private)
    # ------------------------------------------------------------------

    def _check_easa(self, text: str) -> Dict[str, Any]:
        """Check easa compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["easa"] if kw in text.lower()]
        return {
            "regulation": "easa",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_faa_part_121(self, text: str) -> Dict[str, Any]:
        """Check faa part 121 compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["faa_part_121"] if kw in text.lower()]
        return {
            "regulation": "faa_part_121",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_icao_sms(self, text: str) -> Dict[str, Any]:
        """Check icao sms compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["icao_sms"] if kw in text.lower()]
        return {
            "regulation": "icao_sms",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_etops(self, text: str) -> Dict[str, Any]:
        """Check etops compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["etops"] if kw in text.lower()]
        return {
            "regulation": "etops",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_carbon_offsetting(self, text: str) -> Dict[str, Any]:
        """Check carbon offsetting compliance."""
        found = [kw for kw in COMPLIANCE_KEYWORDS["carbon_offsetting"] if kw in text.lower()]
        return {
            "regulation": "carbon_offsetting",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    # ------------------------------------------------------------------
    # RISK SCORING (private)
    # ------------------------------------------------------------------

    def _score_airworthiness_risk(self, text: str) -> RiskScore:
        """Score airworthiness risk."""
        data = _rk.check_risk_keywords(text).get("airworthiness_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="airworthiness_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_operational_risk(self, text: str) -> RiskScore:
        """Score operational risk."""
        data = _rk.check_risk_keywords(text).get("operational_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="operational_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_maintenance_risk(self, text: str) -> RiskScore:
        """Score maintenance risk."""
        data = _rk.check_risk_keywords(text).get("maintenance_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="maintenance_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_financial_risk(self, text: str) -> RiskScore:
        """Score financial risk."""
        data = _rk.check_risk_keywords(text).get("financial_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="financial_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    def _score_reputational_risk(self, text: str) -> RiskScore:
        """Score reputational risk."""
        data = _rk.check_risk_keywords(text).get("reputational_risk", {})
        score = data.get("score", 0.0)
        indicators = data.get("indicators", [])
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="reputational_risk",
            score=round(score, 2),
            level=level,
            indicators=indicators[:5],
            confidence=data.get("confidence", 0.0),
        )

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    def _compute_overall_risk(self, text: str) -> RiskScore:
        """Compute overall risk from individual risk scores."""
        risks = _rk.check_risk_keywords(text)
        total = sum(r.get("score", 0.0) for r in risks.values())
        count = len(risks) or 1
        score = total / count
        level = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return RiskScore(
            category="overall_risk",
            score=round(score, 2),
            level=level,
            indicators=[],
            confidence=round(min(1.0, score + 0.1), 2),
        )
