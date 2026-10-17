"""Commissioning Evidence Classifier — three-valued fraud-aware evidence
classification, ported from <private-repo> ``reasoning/evidence.py``.

Ported: the A/B/C/D/Unprovable classes, PASS/FAIL/UNPROVABLE verdicts, and
the §9 mechanisms for fire-pump and fire-life-safety packets (test-line-to-
tank, covers/clips obscuring the nameplate, serial mismatch, stale
unwitnessed factory test, integrated C&E chain). The domain-kit JSON layer
is replaced by the invalidity ids + remediation text inline.
"""
from __future__ import annotations

from typing import Any, Dict

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "evidence_classifier", "status": status, "result": result, "error": error, "detail": detail}


FIRE_PUMP_COVER_TAGS = {"cover_closed", "clip_obscuring_nameplate", "plastic_wrap_on_plate"}


def _packet(raw) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return {}


class EvidenceClassifierBlock(UniversalBlock):
    """Three-valued fraud-aware commissioning evidence classifier."""

    name = "evidence_classifier"
    version = "1.0.0"
    description = (
        "Commissioning evidence classifier ported from <private-repo> "
        "reasoning/evidence.py: A/B/C/D/Unprovable classes with PASS/FAIL/"
        "UNPROVABLE verdicts for fire-pump and fire-life-safety packets "
        "(test-line-to-tank, covers/clips obscuring the nameplate, serial "
        "mismatch, stale unwitnessed factory test, integrated C&E chain)."
    )
    layer = 3
    tags = ["evidence", "commissioning", "fraud-aware", "hotelops"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "classify", "packet": {"asset_type": "fire_pump", "test_line_to_tank": true, "documents": []}}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "classify")).lower()
        try:
            if action == "classify":
                return _envelope("ok", classify_evidence(payload.get("packet") or {}))
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["classify"]})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)


def classify_evidence(raw: Dict[str, Any]) -> Dict[str, Any]:
    packet = _packet(raw)
    asset_type = str(packet.get("asset_type", ""))
    docs = packet.get("documents") or []

    if asset_type in ("fire_life_safety", "fls", "ce_matrix"):
        if packet.get("individual_tests_pass") and packet.get("integrated_interface_test") is not True:
            return {
                "evidence_class": "Unprovable",
                "verdict": "UNPROVABLE",
                "reasons": ["§9.4.1 Individual tests passed; integrated interfaced response is unproven."],
                "invalidity_ids": ["INV-CE-UNIT-NOT-INTEGRATED"],
                "remediation": ["Run the integrated cause-and-effect response test with a witness."],
            }
        if packet.get("integrated_interface_test") is True:
            return {
                "evidence_class": "A",
                "verdict": "PASS",
                "reasons": ["Integrated C&E chain witnessed (detection→dampers→pressurisation→lifts→door release→BMS)."],
            }

    if asset_type == "fire_pump":
        if packet.get("test_line_to_tank"):
            return {
                "evidence_class": "D",
                "verdict": "FAIL",
                "reasons": ["Fire pump flow certificate is test-line-to-tank — invalid."],
                "invalidity_ids": ["INV-FIRE-PUMP-TEST-TO-TANK"],
                "remediation": ["Re-test on the test header and re-certify."],
            }
        cover_hit = (
            packet.get("covers_clips_removed") is False
            or bool(set(packet.get("photo_tags") or []) & FIRE_PUMP_COVER_TAGS)
            or packet.get("nameplate_readable") is False
        )
        if cover_hit:
            invalid = ["INV-FIRE-PUMP-COVERS-CLIPS"]
            reasons = ["Covers/clips obscure the nameplate or were not removed."]
            if not any(d in docs for d in ("witnessed_commissioning_sheet", "commissioning_report")):
                return {
                    "evidence_class": "Unprovable",
                    "verdict": "UNPROVABLE",
                    "reasons": reasons + ["No independent document remains after photo invalidity."],
                    "invalidity_ids": invalid,
                    "remediation": ["Remove covers/clips and re-photograph the nameplate unobstructed."],
                }
            return {
                "evidence_class": "D",
                "verdict": "FAIL",
                "reasons": reasons + ["Photo is uncontrolled; remaining pack is insufficient for Class A/B."],
                "invalidity_ids": invalid,
                "remediation": ["Remove covers/clips and re-photograph the nameplate unobstructed."],
            }
        serial_on_cert = packet.get("serial_on_certificate")
        serial_on_reg = packet.get("serial_on_register")
        serial_ok = bool(serial_on_cert and serial_on_reg and serial_on_cert == serial_on_reg)
        if serial_on_cert and serial_on_reg and not serial_ok:
            return {
                "evidence_class": "D",
                "verdict": "FAIL",
                "reasons": ["Certificate serial does not match the asset register."],
                "invalidity_ids": ["INV-FIRE-PUMP-SERIAL-MISMATCH"],
                "remediation": ["Correct the register or re-issue the certificate."],
            }
        stale = packet.get("test_age_days") is not None and int(packet.get("test_age_days", 0)) > 365 and not packet.get("site_witness")
        if stale:
            return {
                "evidence_class": "Unprovable",
                "verdict": "UNPROVABLE",
                "reasons": ["Factory test is older than 12 months and was not site-witnessed."],
                "invalidity_ids": ["INV-FIRE-PUMP-STALE-TEST"],
                "remediation": ["Re-test and witness on site."],
            }
        class_a_docs = {"as_built_drawing", "witnessed_commissioning_sheet", "nameplate_photo_unobstructed", "serial_on_asset_register"}
        if class_a_docs.issubset(set(docs)) and serial_ok and packet.get("nameplate_readable") and not packet.get("test_line_to_tank"):
            return {"evidence_class": "A", "verdict": "PASS", "reasons": ["Certified as-built, witnessed test (not to tank), and serial-matched nameplate."]}
        if {"as_built_drawing", "commissioning_report"}.issubset(set(docs)):
            return {"evidence_class": "B", "verdict": "PASS", "reasons": ["As-built plus commissioning report. Sheet-grade Class B — not CD primary evidence."]}
        if "om_manual_or_datasheet" in docs and len(docs) == 1:
            return {"evidence_class": "C", "verdict": "UNPROVABLE", "reasons": ["Vendor literature only — cannot prove the installed asset."]}

    return {"evidence_class": "Unprovable", "verdict": "UNPROVABLE", "reasons": [f"no classifier for asset type '{asset_type}' — evidence cannot be proven"]}
