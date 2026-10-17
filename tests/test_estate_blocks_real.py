"""The five estate blocks must do real work — every fail path proven.

Regression against the echo-stub generation: these blocks used to return
{"status": "ok", "result": <input>} unconditionally. Each test below proves
the failure path AND the success path of the real implementation, exercised
through ``app.blocks.<id>`` directly (``execute(input_data, params)``).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from app.blocks import evidence_verifier as ev_mod
from app.blocks import estate_maintenance as em_mod
from app.blocks.evidence_verifier import EvidenceVerifierBlock
from app.blocks.estate_maintenance import EstateMaintenanceBlock
from app.blocks.estate_registry import EstateRegistryBlock
from app.blocks.portfolio_rollup import PortfolioRollupBlock
from app.blocks.readiness_engine import ReadinessEngineBlock


def run(block_cls, payload: Any, **params: Any) -> Dict[str, Any]:
    """Run one block execution synchronously, the way the registry adapter does."""
    return asyncio.run(block_cls().execute(payload, params or None))


class TestEvidenceVerifier:
    def test_tampered_evidence_fails_verification(self):
        ev_mod.reset_state()
        content = "signed statement"
        stored = run(EvidenceVerifierBlock, {"action": "store", "content": content})
        assert stored["status"] == "ok"
        record_id = stored["result"]["id"]

        # Tamper with the stored evidence in place, then verify.
        ev_mod._records[record_id]["content"] = "tampered!"
        bad = run(EvidenceVerifierBlock, {"action": "verify", "id": record_id})
        assert bad["status"] == "error"
        assert "tampered" in bad["error"]
        assert bad["detail"]["tampered"] is True
        assert bad["result"]["verified"] is False

    def test_verify_success_and_unknown_record_id_errors(self):
        ev_mod.reset_state()
        content = "signed statement"
        stored = run(EvidenceVerifierBlock, {"action": "store", "content": content})
        assert stored["status"] == "ok"
        record_id = stored["result"]["id"]

        good = run(
            EvidenceVerifierBlock,
            {"action": "verify", "id": record_id, "content": content},
        )
        assert good["status"] == "ok"
        assert good["result"]["verified"] is True

        unknown = run(EvidenceVerifierBlock, {"action": "verify", "id": "nope"})
        assert unknown["status"] == "error"
        assert "unknown integrity record" in unknown["error"]


class TestEstateRegistry:
    def test_duplicate_id_is_rejected(self, tmp_path):
        first = run(
            EstateRegistryBlock,
            {"action": "create", "id": "est-1", "data": {"name": "Manor"}},
            store_dir=str(tmp_path),
        )
        assert first["status"] == "ok"
        dup = run(
            EstateRegistryBlock,
            {"action": "create", "id": "est-1", "data": {"name": "Again"}},
            store_dir=str(tmp_path),
        )
        assert dup["status"] == "error"
        assert "duplicate" in dup["error"]
        assert dup["detail"]["duplicate"] is True

    def test_read_back_returns_the_stored_record(self, tmp_path):
        created = run(
            EstateRegistryBlock,
            {"action": "create", "id": "est-2", "data": {"name": "Villa"}},
            store_dir=str(tmp_path),
        )
        assert created["status"] == "ok"
        got = run(
            EstateRegistryBlock,
            {"action": "read", "id": "est-2"},
            store_dir=str(tmp_path),
        )
        assert got["status"] == "ok"
        assert got["result"]["data"]["name"] == "Villa"

        missing = run(
            EstateRegistryBlock,
            {"action": "read", "id": "nope"},
            store_dir=str(tmp_path),
        )
        assert missing["status"] == "error"
        assert "record not found" in missing["error"]


class TestReadinessEngine:
    def test_unmet_checklist_fails_the_gate(self):
        out = run(
            ReadinessEngineBlock,
            {
                "action": "evaluate",
                "checklist": [
                    {"id": "plumbing", "required": True},
                    {"id": "heating", "required": True},
                ],
                "state": {"plumbing": "ok"},
            },
        )
        assert out["status"] == "error"
        assert "heating" in out["error"]
        assert "heating" in out["result"]["unmet"]
        assert out["result"]["ready"] is False

    def test_met_checklist_passes(self):
        out = run(
            ReadinessEngineBlock,
            {
                "action": "evaluate",
                "checklist": [
                    {"id": "plumbing", "required": True},
                    {"id": "heating", "required": False},
                ],
                "state": {"plumbing": "ok"},
            },
        )
        assert out["status"] == "ok"
        assert out["result"]["ready"] is True
        assert out["result"]["satisfied"] == ["plumbing", "heating"]


class TestEstateMaintenance:
    def test_unknown_work_order_id_is_an_error(self):
        em_mod.reset_state()
        out = run(EstateMaintenanceBlock, {"action": "complete", "id": "wo-nope"})
        assert out["status"] == "error"
        assert "unknown work order id" in out["error"]

    def test_create_requires_title(self):
        em_mod.reset_state()
        out = run(EstateMaintenanceBlock, {"action": "create", "due": "2026-10-01"})
        assert out["status"] == "error"
        assert "title is required" in out["error"]

    def test_create_list_complete_round_trip(self):
        em_mod.reset_state()
        created = run(
            EstateMaintenanceBlock,
            {"action": "create", "title": "Roof", "due": "2026-10-01"},
        )
        assert created["status"] == "ok"
        run(
            EstateMaintenanceBlock,
            {"action": "create", "title": "Garden", "due": "2026-09-01"},
        )
        listed = run(EstateMaintenanceBlock, {"action": "list"})
        assert listed["status"] == "ok"
        titles = [w["title"] for w in listed["result"]["orders"]]
        assert titles == ["Garden", "Roof"]  # sorted by due, earliest first

        done = run(
            EstateMaintenanceBlock,
            {"action": "complete", "id": created["result"]["id"]},
        )
        assert done["status"] == "ok"
        assert done["result"]["status"] == "completed"


class TestPortfolioRollup:
    def test_aggregation_sums_and_groups(self):
        out = run(
            PortfolioRollupBlock,
            {
                "properties": [
                    {"id": "a", "value": 100, "status": "active"},
                    {"id": "b", "value": 200, "status": "active"},
                    {"id": "c", "value": 50, "status": "sold"},
                ]
            },
        )
        assert out["status"] == "ok"
        result = out["result"]
        assert result["count"] == 3
        assert result["total_value"] == 350
        assert result["by_status"]["active"] == {"count": 2, "total_value": 300}
        assert result["by_status"]["sold"]["count"] == 1

    def test_non_numeric_values_fail_with_invalid_records(self):
        out = run(
            PortfolioRollupBlock,
            {
                "properties": [
                    {"id": "a", "value": 100, "status": "active"},
                    {"id": "b", "value": "not-a-number"},
                ]
            },
        )
        assert out["status"] == "error"
        assert len(out["detail"]["invalid_records"]) == 1
        assert out["detail"]["invalid_records"][0]["id"] == "b"
        # The valid record is still aggregated honestly.
        assert out["result"]["total_value"] == 100
        assert out["result"]["count"] == 1

    def test_empty_input_is_honest_zeros(self):
        out = run(PortfolioRollupBlock, {"properties": []})
        assert out["status"] == "ok"
        assert out["result"]["count"] == 0
        assert out["result"]["total_value"] == 0
        assert out["result"]["by_status"] == {}
