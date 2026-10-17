"""Regression checks for the insurance kit v2 manifest."""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KIT_DIR = PROJECT_ROOT / "block_store" / "kits" / "insurance"
MANIFEST_PATH = KIT_DIR / "manifest.json"
BUNDLE_DIR = KIT_DIR / "bundle"

REQUIRED_BLOCKS = {
    "pdf",
    "ocr",
    "chat",
    "image",
    "insurance_v2",
    "formula_executor_v2",
    "agency_hierarchy",
    "producer_record",
    "agency_commission_engine",
    "channel_router",
    "attrition_scorer",
    "incentive_targeting",
    "hkia_gn16_rules",
    "bordereaux_ingest",
    "distribution_analytics",
}

# Platform support blocks belong to the host runtime, not this kit's virgin-boot specs.
UNSUPPORTED_PLATFORM_BLOCKS = {
    "workflow",
    "database",
    "audit",
    "notification",
    "recommendation_template",
    "validation_pipeline",
    "webhook",
    "storage",
    "dashboard",
}

REQUIRED_PLAYBOOKS = {
    "app/playbooks/distribution.json",
    "app/playbooks/compensation.json",
    "app/playbooks/compliance.json",
    "app/playbooks/analytics.json",
}


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_insurance_manifest_is_v2_available_suite():
    manifest = _manifest()

    assert manifest["id"] == "insurance"
    assert manifest["version"] == "2.0.0"
    assert manifest["name"] == "Insurance Distribution & Agency Suite"
    assert manifest["status"] == "available"
    assert manifest["source"]["publish_script"] == "scripts/publish_insurance_kit.py"


def test_insurance_manifest_has_required_v2_blocks():
    manifest = _manifest()
    advertised = set(manifest["blocks"])

    assert REQUIRED_BLOCKS.issubset(advertised)
    assert advertised.isdisjoint(UNSUPPORTED_PLATFORM_BLOCKS)


def test_insurance_manifest_playbooks_exist_with_triads():
    manifest = _manifest()
    manifest_playbooks = set(manifest.get("playbooks", []))

    assert REQUIRED_PLAYBOOKS.issubset(manifest_playbooks)
    for rel_path in REQUIRED_PLAYBOOKS:
        playbook_path = BUNDLE_DIR / rel_path
        assert playbook_path.exists()
        playbook = json.loads(playbook_path.read_text(encoding="utf-8"))
        assert {"sop", "escalation", "memory_policy"}.issubset(playbook)
