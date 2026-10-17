"""Hotel Block v2 - TypedBlock implementation

This is the v2 implementation that:
- Extends TypedBlock instead of UniversalContainer
- Accepts TextContent input (from pdf_v2, ocr_v2, etc.)
- Outputs HotelAnalysis type
- Has a single process() entry point instead of action routing
- Internal methods are private (_ prefixed)
- Uses deterministic regex + math, no LLM calls, no external APIs
"""

import re
import math
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, date

from app.core.domain_block_v2 import DomainBlockV2
from app.core.schema_registry import TextContent, HotelAnalysis

from app.core.hotel_knowledge import HotelKnowledge

_hk = HotelKnowledge()


class HotelBlockV2(DomainBlockV2):
    """
    Hotel Block v2 - TypedBlock implementation for hospitality document analysis.

    Input: TextContent (extracted document text)
    Output: HotelAnalysis (entities, metrics, financials, compliance flags, risk scores)
    """

    name = "hotel_v2"
    version = "2.0"
    description = "Hotel management document analysis with typed input/output"
    layer = 3
    tags = ["domain", "hotel", "hospitality", "v2"]
    requires = []

    default_config = {
        "confidence_threshold": 0.85,
    }

    # Input: TextContent from pdf_v2, ocr_v2, etc.
    input_schema = TextContent

    # Output: HotelAnalysis
    output_schema = HotelAnalysis

    # Type declarations for orchestrator
    accepted_input_types = ["TextContent", "PDFContent"]
    produced_output_types = ["HotelAnalysis"]

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste hotel document text...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "adr", "type": "number", "label": "ADR", "unit": "$"},
                {"name": "revpar", "type": "number", "label": "RevPAR", "unit": "$"},
                {"name": "occupancy_rate", "type": "percentage", "label": "Occupancy"},
                {"name": "goppar", "type": "number", "label": "GOPPAR", "unit": "$"},
                {"name": "overbooking_risk", "type": "number", "label": "Overbooking Risk"},
                {"name": "revenue_leakage", "type": "number", "label": "Revenue Leakage"},
                {"name": "fraud_risk", "type": "number", "label": "Fraud Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📊", "label": "Analyze Revenue Report", "prompt": "Analyze this hotel revenue report"},
            {"icon": "🧾", "label": "Check Guest Folio", "prompt": "Check this guest folio for charges and discrepancies"},
            {"icon": "⚠️", "label": "Score Operational Risks", "prompt": "Score operational risks for this hotel document"},
            {"icon": "✅", "label": "Check Compliance", "prompt": "Check this hotel document for compliance flags"},
        ],
    }

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """
        Main entry point - analyze hotel document text.

        Input: TextContent dict (or string for backward compatibility)
        Output: HotelAnalysis dict
        """
        params = params or {}

        # Extract text from TextContent format (or plain string)
        text = self._extract_text(input_data)
        if not text:
            return self._empty_analysis("No text provided")

        # Load any user-supplied custom rules
        custom_rules = params.get("custom_rules") or params.get("rules")
        if custom_rules:
            _hk.set_custom_rules(custom_rules)

        # Determine analysis type from params or auto-detect
        document_type = params.get("document_type") or params.get("analysis_type") or self._detect_document_type(text)

        # Run analysis based on type
        if document_type == "reservation":
            return await self._analyze_reservation(text, params)
        elif document_type == "guest_folio":
            return await self._analyze_guest_folio(text, params)
        elif document_type == "housekeeping_report":
            return await self._analyze_housekeeping_report(text, params)
        elif document_type == "maintenance_request":
            return await self._analyze_maintenance_request(text, params)
        elif document_type == "revenue_report":
            return await self._analyze_revenue_report(text, params)
        elif document_type == "group_contract":
            return await self._analyze_group_contract(text, params)
        elif document_type == "ota_agreement":
            return await self._analyze_ota_agreement(text, params)
        elif document_type == "night_audit":
            return await self._analyze_night_audit(text, params)
        else:
            return await self._analyze_generic(text, params)

    # ------------------------------------------------------------------
    # TEXT EXTRACTION
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DOCUMENT TYPE DETECTION
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        """Auto-detect hotel document type from content.

        More-specific categories (OTA, group, night audit) are checked before
        broader categories (reservation, revenue report) to avoid false matches.
        """
        text_lower = text[:5000].lower()

        # Group contracts / RFPs
        if any(kw in text_lower for kw in ["group booking", "group block", "conference", "banquet", "meeting room", "rfp", "request for proposal"]):
            return "group_contract"

        # Night audit — checked before generic revenue report
        if any(kw in text_lower for kw in ["night audit", "end of day", "batch", "reconciliation", "trial balance"]):
            return "night_audit"

        # Guest folio
        if any(kw in text_lower for kw in ["folio", "invoice", "bill", "charges", "room charge", "minibar", "laundry"]):
            return "guest_folio"

        # Housekeeping report
        if any(kw in text_lower for kw in ["housekeeping", "room status", "clean", "dirty", "inspected", "turndown"]):
            return "housekeeping_report"

        # Maintenance request
        if any(kw in text_lower for kw in ["maintenance", "repair", "out of order", "hvac", "plumbing", "electrical"]):
            return "maintenance_request"

        # Reservation / booking confirmation (checked before revenue_report so confirmations with revenue data are still reservations)
        if any(kw in text_lower for kw in ["reservation", "booking confirmation", "confirmation", "check-in", "check-out", "arrival", "departure"]):
            return "reservation"

        # Revenue report
        if any(kw in text_lower for kw in ["revenue", "adr", "revpar", "occupancy", "daily report"]):
            return "revenue_report"

        # OTA agreements — require business terms to avoid overriding reservation confirmations
        if any(kw in text_lower for kw in ["commission", "rate parity", "net rate", "ota agreement", "ota contract", "ota terms"]) or any(kw in text_lower for kw in ["ota", "booking.com", "expedia", "hotels.com", "agoda"]):
            return "ota_agreement"

        return "generic"

    # ------------------------------------------------------------------
    # ANALYSIS METHODS (private)
    # ------------------------------------------------------------------

    async def _analyze_reservation(self, text: str, params: Dict) -> Dict:
        """Analyze reservation confirmation text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "reservation"
        # Compute length of stay if dates are present
        result["metrics"]["length_of_stay"] = self._extract_length_of_stay_from_text(text)
        return self._finalize_result(result, params)

    async def _analyze_guest_folio(self, text: str, params: Dict) -> Dict:
        """Analyze guest folio / invoice text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "guest_folio"
        return self._finalize_result(result, params)

    async def _analyze_housekeeping_report(self, text: str, params: Dict) -> Dict:
        """Analyze housekeeping report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "housekeeping_report"
        return self._finalize_result(result, params)

    async def _analyze_maintenance_request(self, text: str, params: Dict) -> Dict:
        """Analyze maintenance request text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "maintenance_request"
        return self._finalize_result(result, params)

    async def _analyze_revenue_report(self, text: str, params: Dict) -> Dict:
        """Analyze revenue / night audit report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "revenue_report"
        return self._finalize_result(result, params)

    async def _analyze_group_contract(self, text: str, params: Dict) -> Dict:
        """Analyze group booking / RFP text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "group_contract"
        return self._finalize_result(result, params)

    async def _analyze_ota_agreement(self, text: str, params: Dict) -> Dict:
        """Analyze OTA agreement text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "ota_agreement"
        return self._finalize_result(result, params)

    async def _analyze_night_audit(self, text: str, params: Dict) -> Dict:
        """Analyze night audit report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "night_audit"
        return self._finalize_result(result, params)

    async def _analyze_generic(self, text: str, params: Dict) -> Dict:
        """Generic analysis for unknown hotel document types."""
        result = self._build_analysis(text, params)
        result["document_type"] = "generic"
        return self._finalize_result(result, params)

    # ------------------------------------------------------------------
    # BUILDERS
    # ------------------------------------------------------------------

    def _build_analysis(self, text: str, params: Dict) -> Dict:
        """Run all extraction passes and return a working dict."""
        entities = {
            "guest_names": self._extract_guest_names(text),
            "reservation_numbers": self._extract_reservation_numbers(text),
            "room_numbers": self._extract_room_numbers(text),
            "rate_codes": self._extract_rate_codes(text),
            "confirmation_numbers": self._extract_confirmation_numbers(text),
            "loyalty_numbers": self._extract_loyalty_numbers(text),
            "ota_names": self._extract_ota_names(text),
        }
        financials = self._extract_financials(text)
        metrics = self._calculate_metrics(text, params, financials)
        compliance_flags = {
            "pci_dss": self._check_pci_dss(text),
            "gdpr": self._check_gdpr_guest_data(text),
            "local_hospitality": self._check_local_hospitality_reg(text),
            "tax_compliance": self._check_tax_compliance(text),
        }
        risk_scores = {
            "overbooking_risk": self._score_overbooking_risk(text),
            "revenue_leakage": self._score_revenue_leakage(text),
            "fraud_risk": self._score_fraud_risk(text),
            "maintenance_backlog": self._score_maintenance_backlog(text),
            "reputation_risk": self._score_reputation_risk(text),
            "overall_risk": self._compute_overall_risk(text),
        }
        custom_rule_hits = _hk.check_custom_rules(text)
        hotel_name = self._extract_hotel_name(text)

        return {
            "document_type": "unknown",
            "entities": entities,
            "metrics": metrics,
            "financials": financials,
            "compliance_flags": compliance_flags,
            "risk_scores": risk_scores,
            "custom_rule_hits": custom_rule_hits,
            "text": text,
            "raw_text": text[:2000] if params.get("include_raw") else "",
            "metadata": {
                "extracted_at": self._timestamp(),
                "entity_count": sum(len(v) for v in entities.values()),
                "metric_count": sum(1 for v in metrics.values() if v and v.get("value") is not None),
                "hotel_name": hotel_name,
            },
        }

    # ------------------------------------------------------------------
    # ENTITY EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_guest_names(self, text: str) -> List[Dict]:
        """Extract guest names from salutations and labels."""
        found = []

        # Pattern: Mr./Mrs./Ms./Dr. + name
        salutation_pattern = r"\b(Mr\.?|Mrs\.?|Ms\.?|Dr\.?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)"
        for match in re.finditer(salutation_pattern, text):
            name = f"{match.group(1)} {match.group(2)}"
            found.append({
                "type": "guest_name",
                "value": name,
                "confidence": 0.9,
                "context": text[max(0, match.start() - 30):match.end() + 30],
            })

        # Pattern: "Guest Name:", "Reserved for:", "Primary Guest:"
        label_pattern = r"(?:guest name|reserved for|primary guest)[:\s]+((?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?\s+)?[A-Z][a-zA-Z\s\.]+?)(?:\n|$|,|;)"
        for match in re.finditer(label_pattern, text, re.IGNORECASE):
            name = match.group(1).strip()
            # Reject anything that looks like a sentence fragment
            if len(name) > 2 and len(name) < 60 and not any(bad in name.lower() for bad in ["policy", "retention", "compliance", "reviewed", "data", "invoice", "charge"]):
                found.append({
                    "type": "guest_name",
                    "value": name,
                    "confidence": 0.85,
                    "context": text[max(0, match.start() - 30):match.end() + 30],
                })

        return self._deduplicate_entities(found)

    def _extract_reservation_numbers(self, text: str) -> List[Dict]:
        """Extract reservation/confirmation numbers (6-10 digits) with context."""
        pattern = r"\b\d{6,10}\b"
        context_keywords = ["confirmation", "reservation", "booking ref", "booking reference", "resv"]
        found = []

        loyalty_programs = ["hilton honors", "marriott bonvoy", "ihg rewards", "world of hyatt", "le club accor", "choice privileges", "wyndham rewards", "best western rewards"]
        for match in re.finditer(pattern, text):
            ctx = text[max(0, match.start() - 80):match.end() + 80]
            has_context = any(kw in ctx.lower() for kw in context_keywords)
            # Skip if this number sits right after a loyalty program name
            preceding = text[max(0, match.start() - 40):match.start()].lower()
            is_loyalty = any(kw in preceding for kw in loyalty_programs)
            if is_loyalty:
                continue
            found.append({
                "type": "reservation_number",
                "value": match.group(0),
                "confidence": 0.85 if has_context else 0.5,
                "context": ctx,
            })

        return self._deduplicate_entities(found)

    def _extract_room_numbers(self, text: str) -> List[Dict]:
        """Extract room and suite identifiers."""
        found = []

        room_pattern = r"\b(room|rm\.?|suite)\s*:?\s*(?:#)?\s*(\d{3,4}|[A-Z]?\d{2,4})\b"
        for match in re.finditer(room_pattern, text, re.IGNORECASE):
            found.append({
                "type": "room_number",
                "value": f"{match.group(1).title()} {match.group(2)}",
                "confidence": 0.9,
                "context": text[max(0, match.start() - 30):match.end() + 30],
            })

        floor_pattern = r"\b(floor)\s*(\d{1,2})\b"
        for match in re.finditer(floor_pattern, text, re.IGNORECASE):
            found.append({
                "type": "floor",
                "value": f"Floor {match.group(2)}",
                "confidence": 0.8,
                "context": text[max(0, match.start() - 20):match.end() + 20],
            })

        return self._deduplicate_entities(found)

    def _extract_rate_codes(self, text: str) -> List[Dict]:
        """Extract rate codes and promotional codes."""
        known_codes = ["BAR", "CORP", "GOV", "AAA", "AARP", "SENIOR", "MILITARY", "STAFF", "COMP", "PKG"]
        found = []
        text_upper = text.upper()

        # Known codes as whole words
        for code in known_codes:
            for match in re.finditer(rf"\b{code}\b", text_upper):
                orig_start = match.start()
                orig_end = match.end()
                found.append({
                    "type": "rate_code",
                    "value": code,
                    "confidence": 0.9,
                    "context": text[max(0, orig_start - 40):orig_end + 40],
                })

        # Generic promo/package codes near labels
        promo_pattern = r"(?:rate code|promo code|package code)[:\s]+([A-Z0-9\-]{2,20})"
        for match in re.finditer(promo_pattern, text, re.IGNORECASE):
            found.append({
                "type": "rate_code",
                "value": match.group(1),
                "confidence": 0.85,
                "context": text[max(0, match.start() - 30):match.end() + 30],
            })

        return self._deduplicate_entities(found)

    def _extract_confirmation_numbers(self, text: str) -> List[Dict]:
        """Extract alphanumeric confirmation / reference numbers."""
        pattern = r"\b[A-Z0-9]{6,12}\b"
        context_keywords = ["confirmation", "confirm", "ref number", "reference", "booking ref"]
        found = []

        for match in re.finditer(pattern, text):
            token = match.group(0)
            if token.isdigit():
                continue  # handled by reservation_numbers
            ctx = text[max(0, match.start() - 80):match.end() + 80]
            has_context = any(kw in ctx.lower() for kw in context_keywords)
            found.append({
                "type": "confirmation_number",
                "value": token,
                "confidence": 0.8 if has_context else 0.45,
                "context": ctx,
            })

        return self._deduplicate_entities(found)

    def _extract_loyalty_numbers(self, text: str) -> List[Dict]:
        """Extract loyalty program numbers near program names."""
        programs = [
            "Hilton Honors", "Marriott Bonvoy", "IHG Rewards", "World of Hyatt",
            "Le Club Accor", "Choice Privileges", "Wyndham Rewards", "Best Western Rewards"
        ]
        found = []
        text_lower = text.lower()

        for program in programs:
            prog_lower = program.lower()
            for match in re.finditer(re.escape(prog_lower), text_lower):
                start = match.end()
                window = text[start:start + 60]
                num_match = re.search(r"\b\d{9,12}\b", window)
                if num_match:
                    found.append({
                        "type": "loyalty_number",
                        "value": f"{program}: {num_match.group(0)}",
                        "confidence": 0.9,
                        "context": text[max(0, match.start() - 20):start + num_match.end() + 10],
                        "metadata": {"program": program, "number": num_match.group(0)},
                    })

        return found

    def _extract_ota_names(self, text: str) -> List[Dict]:
        """Detect OTA / booking channel names."""
        ota_list = [
            "Booking.com", "Expedia", "Hotels.com", "Agoda", "TripAdvisor",
            "Airbnb", "Vrbo", "Priceline", "Kayak", "Trivago", "Orbitz", "Travelocity"
        ]
        found = []
        text_lower = text.lower()

        for ota in ota_list:
            # Handle domain-style names with escaped dot
            pattern = re.escape(ota.lower()).replace(r"\.", r"\.?")
            for match in re.finditer(pattern, text_lower):
                orig_start = match.start()
                orig_end = min(len(text), orig_start + len(ota))
                found.append({
                    "type": "ota_name",
                    "value": ota,
                    "confidence": 0.95,
                    "context": text[max(0, orig_start - 30):orig_end + 30],
                })

        # Generic OTA mention
        if "ota" in text_lower and not any(o.lower() in text_lower for o in ota_list):
            found.append({
                "type": "ota_name",
                "value": "OTA (generic)",
                "confidence": 0.6,
                "context": text,
            })

        return self._deduplicate_entities(found)

    def _extract_hotel_name(self, text: str) -> Optional[str]:
        """Best-effort hotel name extraction."""
        patterns = [
            r"(?:hotel name|property|property name)[:\s\-]+([A-Z][A-Za-z0-9\s&\.]+?)(?:\n|$)",
            r"^\s*([A-Z][A-Za-z0-9\s&\.]+(?:Hotel|Resort|Inn|Suites|Lodge|Spa))",
            r"(?:Confirmation\s*-\s*|Reservation\s*-\s*)([A-Z][A-Za-z0-9\s&\.]+(?:Hotel|Resort|Inn|Suites|Lodge|Spa))",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(1).strip()[:100]
        return None

    # ------------------------------------------------------------------
    # FINANCIAL VALUE EXTRACTION
    # ------------------------------------------------------------------

    def _extract_financials(self, text: str) -> Dict[str, Optional[float]]:
        """Extract headline financial figures from text."""
        return {
            "total_revenue": self._find_money("total revenue|total sales", text),
            "room_revenue": self._find_money("room revenue|rooms revenue", text),
            "f_b_revenue": self._find_money("f&b revenue|food and beverage|f b revenue", text),
            "other_revenue": self._find_money("other revenue|miscellaneous revenue", text),
            "taxes": self._find_money("tax|taxes|vat", text),
            "total_charges": self._find_money("total charges|total amount|balance due", text),
        }

    def _find_money(self, label_pattern: str, text: str) -> Optional[float]:
        """Find a monetary value following a label pattern."""
        pattern = rf"(?:{label_pattern})\s*[:\-\(]?\s*[\$\u20ac£¥]?\s*([\-]?\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{1,2}})?|\d+(?:\.\d{{1,2}})?)\s*(million|billion|thousand|m|bn|b|k)?"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            number_str = match.group(1).replace(",", "")
            try:
                value = float(number_str)
            except ValueError:
                continue
            multiplier = match.group(2)
            if multiplier:
                mlower = multiplier.lower()
                if mlower in {"million", "m"}:
                    value *= 1_000_000
                elif mlower in {"billion", "bn", "b"}:
                    value *= 1_000_000_000
                elif mlower in {"thousand", "k"}:
                    value *= 1_000
            return value
        return None

    # ------------------------------------------------------------------
    # METRICS & FORMULAS (private)
    # ------------------------------------------------------------------

    def _calculate_metrics(self, text: str, params: Dict, financials: Dict) -> Dict[str, Any]:
        """Calculate hotel KPIs from explicit params or extracted values."""
        total_revenue = params.get("total_revenue") or financials.get("total_revenue") or financials.get("room_revenue")
        room_revenue = params.get("room_revenue") or financials.get("room_revenue") or total_revenue
        rooms_sold = params.get("rooms_sold") or self._extract_number_near(text, ["rooms sold", "rooms occupied"])
        total_rooms = params.get("total_rooms") or self._extract_number_near(text, ["total rooms", "available rooms", "room inventory"])
        gross_profit = params.get("gross_profit") or self._find_money("gross profit|gop", text)
        no_shows = params.get("no_shows") or self._extract_number_near(text, ["no show", "no-show"])
        cancellations = params.get("cancellations") or self._extract_number_near(text, ["cancellation", "cancelled"])
        total_bookings = params.get("total_bookings") or self._extract_number_near(text, ["total bookings", "total reservations"])
        walk_ins = params.get("walk_ins") or self._extract_number_near(text, ["walk in", "walk-in"])
        total_arrivals = params.get("total_arrivals") or self._extract_number_near(text, ["total arrivals", "arrivals"])

        return {
            "adr": self._extract_adr(room_revenue, rooms_sold),
            "revpar": self._extract_revpar(room_revenue, total_rooms),
            "occupancy_rate": self._extract_occupancy(rooms_sold, total_rooms),
            "goppar": self._extract_goppar(gross_profit, total_rooms),
            "length_of_stay": self._extract_length_of_stay_from_text(text),
            "no_show_rate": self._extract_no_show_rate(no_shows, total_bookings),
            "cancellation_rate": self._extract_cancellation_rate(cancellations, total_bookings),
            "walk_in_rate": self._extract_walk_ins(walk_ins, total_arrivals),
        }

    def _extract_number_near(self, text: str, labels: List[str]) -> Optional[float]:
        """Extract a number near one of the given labels."""
        label_pattern = "|".join(re.escape(label) for label in labels)
        pattern = rf"(?:{label_pattern})[:\s]+([\-]?\d{{1,3}}(?:,\d{{3}})*(?:\.\d+)?|\d+(?:\.\d+)?)"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                continue
        return None

    def _extract_adr(self, revenue: Optional[float], rooms_sold: Optional[float]) -> Dict[str, Any]:
        if revenue is None or rooms_sold is None or rooms_sold == 0:
            return {"name": "adr", "value": None, "inputs": {"revenue": revenue, "rooms_sold": rooms_sold}, "error": "Missing revenue or rooms sold"}
        return {"name": "adr", "value": round(revenue / rooms_sold, 2), "inputs": {"revenue": revenue, "rooms_sold": rooms_sold}, "unit": "$", "confidence": 1.0}

    def _extract_revpar(self, revenue: Optional[float], total_rooms: Optional[float]) -> Dict[str, Any]:
        if revenue is None or total_rooms is None or total_rooms == 0:
            return {"name": "revpar", "value": None, "inputs": {"revenue": revenue, "total_rooms": total_rooms}, "error": "Missing revenue or total rooms"}
        return {"name": "revpar", "value": round(revenue / total_rooms, 2), "inputs": {"revenue": revenue, "total_rooms": total_rooms}, "unit": "$", "confidence": 1.0}

    def _extract_occupancy(self, rooms_sold: Optional[float], total_rooms: Optional[float]) -> Dict[str, Any]:
        if rooms_sold is None or total_rooms is None or total_rooms == 0:
            return {"name": "occupancy_rate", "value": None, "inputs": {"rooms_sold": rooms_sold, "total_rooms": total_rooms}, "error": "Missing rooms sold or total rooms"}
        return {"name": "occupancy_rate", "value": round(rooms_sold / total_rooms * 100, 2), "inputs": {"rooms_sold": rooms_sold, "total_rooms": total_rooms}, "unit": "%", "confidence": 1.0}

    def _extract_goppar(self, gross_profit: Optional[float], total_rooms: Optional[float]) -> Dict[str, Any]:
        if gross_profit is None or total_rooms is None or total_rooms == 0:
            return {"name": "goppar", "value": None, "inputs": {"gross_profit": gross_profit, "total_rooms": total_rooms}, "error": "Missing gross profit or total rooms"}
        return {"name": "goppar", "value": round(gross_profit / total_rooms, 2), "inputs": {"gross_profit": gross_profit, "total_rooms": total_rooms}, "unit": "$", "confidence": 1.0}

    def _extract_length_of_stay(self, arrival: Optional[date], departure: Optional[date]) -> Dict[str, Any]:
        if arrival is None or departure is None:
            return {"name": "length_of_stay", "value": None, "inputs": {"arrival": str(arrival), "departure": str(departure)}, "error": "Missing arrival or departure date"}
        nights = (departure - arrival).days
        return {"name": "length_of_stay", "value": nights, "inputs": {"arrival": str(arrival), "departure": str(departure)}, "unit": "nights", "confidence": 1.0}

    def _extract_length_of_stay_from_text(self, text: str) -> Dict[str, Any]:
        """Extract length of stay from arrival/departure dates in text."""
        arrival = self._extract_date_near(text, ["arrival", "check-in", "check in"])
        departure = self._extract_date_near(text, ["departure", "check-out", "check out"])
        return self._extract_length_of_stay(arrival, departure)

    def _extract_date_near(self, text: str, labels: List[str]) -> Optional[date]:
        """Best-effort date extraction near labels (YYYY-MM-DD, DD/MM/YYYY, MM/DD/YYYY)."""
        label_pattern = "|".join(re.escape(label) for label in labels)
        date_pattern = r"(?:{labels})[:\s]+(\d{{4}}[-/]\d{{1,2}}[-/]\d{{1,2}}|\d{{1,2}}[-/]\d{{1,2}}[-/]\d{{2,4}})"
        match = re.search(date_pattern.format(labels=label_pattern), text, re.IGNORECASE)
        if not match:
            return None
        date_str = match.group(1)
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        return None

    def _extract_no_show_rate(self, no_shows: Optional[float], total_bookings: Optional[float]) -> Dict[str, Any]:
        if no_shows is None or total_bookings is None or total_bookings == 0:
            return {"name": "no_show_rate", "value": None, "inputs": {"no_shows": no_shows, "total_bookings": total_bookings}, "error": "Missing no-shows or total bookings"}
        return {"name": "no_show_rate", "value": round(no_shows / total_bookings * 100, 2), "inputs": {"no_shows": no_shows, "total_bookings": total_bookings}, "unit": "%", "confidence": 1.0}

    def _extract_cancellation_rate(self, cancellations: Optional[float], total_bookings: Optional[float]) -> Dict[str, Any]:
        if cancellations is None or total_bookings is None or total_bookings == 0:
            return {"name": "cancellation_rate", "value": None, "inputs": {"cancellations": cancellations, "total_bookings": total_bookings}, "error": "Missing cancellations or total bookings"}
        return {"name": "cancellation_rate", "value": round(cancellations / total_bookings * 100, 2), "inputs": {"cancellations": cancellations, "total_bookings": total_bookings}, "unit": "%", "confidence": 1.0}

    def _extract_walk_ins(self, walk_ins: Optional[float], total_arrivals: Optional[float]) -> Dict[str, Any]:
        if walk_ins is None or total_arrivals is None or total_arrivals == 0:
            return {"name": "walk_in_rate", "value": None, "inputs": {"walk_ins": walk_ins, "total_arrivals": total_arrivals}, "error": "Missing walk-ins or total arrivals"}
        return {"name": "walk_in_rate", "value": round(walk_ins / total_arrivals * 100, 2), "inputs": {"walk_ins": walk_ins, "total_arrivals": total_arrivals}, "unit": "%", "confidence": 1.0}

    # ------------------------------------------------------------------
    # COMPLIANCE & REGULATORY CHECKING (private)
    # ------------------------------------------------------------------

    def _check_pci_dss(self, text: str) -> Dict[str, Any]:
        """Detect PCI DSS / payment-card mentions."""
        text_lower = text.lower()
        keywords = ["credit card storage", "cvv", "tokenization", "pci dss", "pci compliance", "cardholder data", "encryption"]
        found = [kw for kw in keywords if kw in text_lower]
        return {
            "regulation": "pci_dss",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_gdpr_guest_data(self, text: str) -> Dict[str, Any]:
        """Detect GDPR concepts in a hotel/guest context."""
        text_lower = text.lower()
        keywords = ["guest data retention", "consent", "right to erasure", "data processing", "personal data", "gdpr", "privacy policy"]
        found = [kw for kw in keywords if kw in text_lower]
        return {
            "regulation": "gdpr_guest_data",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_local_hospitality_reg(self, text: str) -> Dict[str, Any]:
        """Detect local hospitality regulation mentions."""
        text_lower = text.lower()
        keywords = ["tourism license", "fire safety", "food hygiene", "accessibility", "health inspection", "safety certificate", "hotel license"]
        found = [kw for kw in keywords if kw in text_lower]
        return {
            "regulation": "local_hospitality",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_tax_compliance(self, text: str) -> Dict[str, Any]:
        """Detect tax / fee disclosure mentions."""
        text_lower = text.lower()
        keywords = ["vat", "tourism tax", "city tax", "resort fee", "service charge", "tax disclosure", "occupancy tax"]
        found = [kw for kw in keywords if kw in text_lower]
        return {
            "regulation": "tax_compliance",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    # ------------------------------------------------------------------
    # RISK & OPERATIONS SCORING (private)
    # ------------------------------------------------------------------

    def _score_overbooking_risk(self, text: str) -> Dict[str, Any]:
        """Score overbooking risk from text indicators."""
        text_lower = text.lower()
        indicators = ["overbook", "walked guest", "walk in", "relocation", "oversold", "compensation"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {
            "category": "overbooking_risk",
            "score": round(score, 2),
            "level": self._risk_level(score),
            "indicators": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _score_revenue_leakage(self, text: str) -> Dict[str, Any]:
        """Score revenue leakage risk."""
        text_lower = text.lower()
        indicators = ["rate discrepancy", "unauthorized discount", "complimentary room", "rate override", "free upgrade", "staff abuse"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {
            "category": "revenue_leakage",
            "score": round(score, 2),
            "level": self._risk_level(score),
            "indicators": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _score_fraud_risk(self, text: str) -> Dict[str, Any]:
        """Score fraud risk."""
        text_lower = text.lower()
        indicators = ["duplicate booking", "fake credit card", "chargeback", "identity fraud", "stolen card", "no show fraud"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {
            "category": "fraud_risk",
            "score": round(score, 2),
            "level": self._risk_level(score),
            "indicators": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _score_maintenance_backlog(self, text: str) -> Dict[str, Any]:
        """Score maintenance backlog risk."""
        text_lower = text.lower()
        indicators = ["out of order", "pending repair", "maintenance request", "safety hazard", "guest complaint", "broken"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {
            "category": "maintenance_backlog",
            "score": round(score, 2),
            "level": self._risk_level(score),
            "indicators": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _score_reputation_risk(self, text: str) -> Dict[str, Any]:
        """Score reputation risk."""
        text_lower = text.lower()
        indicators = ["review score", "bad review", "complaint", "social media", "ota ranking", "tripadvisor", "negative feedback"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {
            "category": "reputation_risk",
            "score": round(score, 2),
            "level": self._risk_level(score),
            "indicators": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _compute_overall_risk(self, text: str) -> Dict[str, Any]:
        """Combine individual risk scores into an overall score."""
        overbooking = self._score_overbooking_risk(text)
        revenue = self._score_revenue_leakage(text)
        fraud = self._score_fraud_risk(text)
        maintenance = self._score_maintenance_backlog(text)
        reputation = self._score_reputation_risk(text)
        avg = (overbooking["score"] + revenue["score"] + fraud["score"] + maintenance["score"] + reputation["score"]) / 5.0
        return {
            "category": "overall_risk",
            "score": round(avg, 2),
            "level": self._risk_level(avg),
            "indicators": overbooking["indicators"] + revenue["indicators"] + fraud["indicators"] + maintenance["indicators"] + reputation["indicators"],
            "confidence": round(min(overbooking["confidence"], revenue["confidence"], fraud["confidence"], maintenance["confidence"], reputation["confidence"]), 2),
        }

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # EMPTY RESULT
    # ------------------------------------------------------------------
