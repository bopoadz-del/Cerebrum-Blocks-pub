"""End-to-end integration tests for domain kits, connectors, and reactive workflows."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ENV", "test")
os.environ.setdefault("CEREBRUM_VIRGIN", "1")


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app, headers={"Authorization": "Bearer cb_dev_key"})


def _reload_registry():
    """Rebuild BLOCK_REGISTRY from whatever the environment now says."""
    import app.blocks as blocks_mod
    import app.core.domain_kit_loader as loader

    importlib.reload(loader)
    importlib.reload(blocks_mod)
    return blocks_mod.BLOCK_REGISTRY


@pytest.fixture(autouse=True)
def _restore_block_registry():
    """Put the registry back the way it was found.

    Every virgin-boot test in this file reloads app.blocks with
    CEREBRUM_VIRGIN=1, which empties BLOCK_REGISTRY *for the rest of the
    pytest session* -- the module object is shared. That is why these tests
    were deselected rather than fixed: unskipping them took unrelated files
    (tests/test_library_container.py) down with them, which looks like a
    flaky suite and is really one test leaking global state.

    Restoring the environment is not enough on its own; the module has to be
    reloaded again afterwards or the emptied registry survives.
    """
    saved = {k: os.environ.get(k) for k in ("CEREBRUM_VIRGIN", "CEREBRUM_DOMAIN_KITS")}
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _reload_registry()


@pytest.fixture
def virgin_block_registry():
    """Reload block registry with virgin boot (no domain kits)."""
    os.environ["CEREBRUM_VIRGIN"] = "1"
    os.environ.pop("CEREBRUM_DOMAIN_KITS", None)
    return _reload_registry()


@pytest.fixture
def tmp_install_target(tmp_path):
    return tmp_path / "cerebrum_instance"


class TestVirginBoot:
    def test_construction_not_in_app_blocks(self):
        """Virgin boot must not ship construction blocks in app/blocks."""
        construction_blocks = [
            "construction_v2",
            "boq_processor",
            "bim",
            "smart_orchestrator",
        ]
        for name in construction_blocks:
            path = ROOT / "app" / "blocks" / f"{name}.py"
            # Virgin strips construction from runtime registry, not necessarily disk.
            # Verify blocks are not registered when CEREBRUM_VIRGIN=1 and no kits enabled.
            os.environ["CEREBRUM_VIRGIN"] = "1"
            os.environ.pop("CEREBRUM_DOMAIN_KITS", None)
            import app.core.domain_kit_loader as loader
            import app.blocks as blocks_mod

            importlib.reload(loader)
            importlib.reload(blocks_mod)
            assert name not in blocks_mod.BLOCK_REGISTRY

    def test_virgin_boot_flag(self):
        from app.core.domain_kit_loader import is_virgin_boot

        os.environ["CEREBRUM_VIRGIN"] = "1"
        os.environ.pop("CEREBRUM_DOMAIN_KITS", None)
        assert is_virgin_boot() is True


class TestMedicalKitInstall:
    def test_install_medical_registers_the_kit(self, tmp_install_target):
        """Install writes the kit into the target's registry.

        This used to also assert that install copied
        app/blocks/medical_ehr_connector.py into the target. It never did,
        for any kit: no bundle in block_store ships a connector, because
        connectors are app-level blocks that domain_kit_loader activates when
        the kit is enabled (see app/core/domain_kit_loader.py). The test was
        asserting a distribution mechanism that does not exist, so it was
        deselected instead of corrected. The connector half is asserted
        against the real mechanism in
        test_the_medical_connector_is_reachable_once_the_kit_is_enabled.
        """
        from app.core.container_kit_store import install_kit

        target = tmp_install_target
        target.mkdir(parents=True)
        result = install_kit("medical", target_root=target, force=True)
        assert result["status"] == "success"
        assert result.get("install_mode") in ("skeleton", "bundle")

        registry_path = target / "data" / "domain_kit_registry.json"
        assert registry_path.exists(), f"install wrote no registry: {result}"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        assert "medical" in registry.get("kits", {})

    def test_the_medical_connector_is_reachable_once_the_kit_is_enabled(self):
        """The property the copy-assertion was reaching for.

        Enabling the kit must make its connector resolvable, because that is
        what "installing the medical kit gets you an EHR connector" means on
        the mechanism this repo actually uses.
        """
        os.environ["CEREBRUM_VIRGIN"] = "0"
        os.environ["CEREBRUM_DOMAIN_KITS"] = "medical"
        registry = _reload_registry()

        assert "medical_ehr_connector" in registry, (
            "enabling the medical kit did not make its connector resolvable: "
            f"{sorted(registry)[:20]}"
        )


class TestMedicalEHRConnector:
    @pytest.mark.asyncio
    async def test_mock_fhir_connector_event(self):
        from app.blocks.medical_ehr_connector import MedicalEHRConnectorBlock

        block = MedicalEHRConnectorBlock(config={
            "fhir_base_url": "https://fhir.test/r4",
            "fhir_access_token": "test-token",
        })

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "resourceType": "Patient",
            "id": "pat-1",
            "name": [{"family": "Doe", "given": ["Jane"]}],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await block.process(
                {"resource": "Patient", "resource_id": "pat-1"},
                {"action": "fetch", "resource": "Patient"},
            )

        assert result["status"] == "success"
        event = result["event"]
        assert event["event_type"] == "fhir.patient.fetched"
        assert event["source"] == "medical_ehr"
        assert event["normalized_data"]["count"] == 1


class TestReactiveVideoWorkflow:
    @pytest.mark.asyncio
    async def test_video_ingest_auto_trigger_fires_notification(self):
        from app.blocks.video_metadata_ingest import VideoMetadataIngestBlock

        mock_notif = AsyncMock()
        mock_notif.process = AsyncMock(return_value={"status": "success", "channel": "webhook", "sent": True})

        ingest = VideoMetadataIngestBlock()
        payload = {
            "camera_id": "lobby-1",
            "source_id": "test",
            "anomalies": [
                {"anomaly_type": "overcrowding", "severity": "high", "confidence": 0.9}
            ],
            "auto_trigger": True,
            "notify_channel": "webhook",
            "notify_to": "https://hooks.example.com/alerts",
        }

        with patch("app.dependencies.get_block_instance", return_value=mock_notif):
            result = await ingest.process(payload, {"action": "ingest"})

        assert result["status"] == "success"
        assert result.get("workflow") is not None
        workflow = result["workflow"]
        assert workflow.get("triggered") is True
        mock_notif.process.assert_called_once()

    def test_video_ingest_api_with_workflow(self, client):
        mock_notif = AsyncMock()
        mock_notif.process = AsyncMock(return_value={"status": "success", "channel": "webhook"})

        with patch("app.dependencies.get_block_instance", return_value=mock_notif):
            response = client.post(
                "/v1/video/ingest",
                json={
                    "camera_id": "api-cam-1",
                    "anomalies": [{"anomaly_type": "intrusion", "severity": "critical"}],
                    "auto_trigger": True,
                    "notify_channel": "webhook",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data.get("anomaly_count", 0) >= 1
        assert data.get("workflow") is not None


class TestStoreCatalog:
    """The catalog must describe kits that exist.

    These two tests used to name six kits by hand -- including `law` and
    `maintenance`, which have never existed in block_store/kits (the legal
    kit is `legal`, and there is no maintenance kit at all) -- and three
    connectors, two of which were never written (`pacer_connector`,
    `cmms_connector`). Deselecting them turned a standing product question
    into a green run.

    Naming kits nobody built is not a test, it is a wish. What is worth
    enforcing, and what these now enforce, is that everything the store
    advertises is real: every listed kit exists on disk, and every block it
    claims to ship can actually be resolved. That goes red the moment the
    catalog starts advertising something that is not there, which is the
    failure the hand-written list was groping for.
    """

    def test_every_advertised_kit_exists_on_disk(self, client):
        response = client.get("/store/containers")
        assert response.status_code == 200
        data = response.json()

        kit_root = ROOT / "block_store" / "kits"
        listed = {k["id"] for k in data["containers"]}
        assert listed, "the store advertises no kits at all"
        assert data["total"] == len(data["containers"])

        missing = sorted(k for k in listed if not (kit_root / k).is_dir())
        assert not missing, f"catalog advertises kits with no source: {missing}"

    def test_every_kit_on_disk_is_advertised(self, client):
        """The other direction: a kit that ships and is never listed is a kit
        nobody can install."""
        kit_root = ROOT / "block_store" / "kits"
        on_disk = {
            d.name
            for d in kit_root.iterdir()
            if d.is_dir() and not d.name.startswith("_") and (d / "manifest.json").is_file()
        }
        listed = {k["id"] for k in client.get("/store/containers").json()["containers"]}

        assert on_disk <= listed, f"kits on disk but not in the catalog: {sorted(on_disk - listed)}"

    def test_every_block_a_kit_advertises_is_declared_somewhere(self, client):
        """A catalog entry promising a block nothing has ever heard of.

        Deliberately not checked against BLOCK_REGISTRY: at test time that is
        the virgin registry, so `agriculture_v2` is legitimately absent until
        the agriculture kit is enabled. Asserting against it would call every
        kit-specific block in the store unresolvable, which says nothing.

        What must hold regardless of which kits are switched on is that the
        name is declared -- as a generic block, or in some kit's spec.
        """
        import app.blocks as blocks_mod
        from app.core.domain_kit_loader import _KIT_BLOCK_SPECS

        known = set(blocks_mod._GENERIC_BLOCK_DEFS)
        known |= set(getattr(blocks_mod, "_EXTENDED_BLOCK_DEFS", {}))
        for entries in _KIT_BLOCK_SPECS.values():
            known |= {name for name, _module, _cls in entries}

        kit_root = ROOT / "block_store" / "kits"

        def _shipped_by(kit_id: str) -> set[str]:
            """Blocks a kit carries in its own tree.

            Not every kit distributes through _KIT_BLOCK_SPECS. universal_kernel
            ships 23 blocks as wave<N>/<name>/code.py with their own
            kernel_manifest.json and tests -- real blocks, simply not app
            modules. Kit-first work (mep_coordination) ships the same way
            domain kits do: bundle/app/blocks/<name>.py. A check that only
            knew about app modules would call those phantom, which is the
            opposite of the truth.
            """
            base = kit_root / kit_id
            if not base.is_dir():
                return set()
            found = {p.stem for p in base.glob("blocks/*.py") if p.stem != "__init__"}
            found |= {
                p.stem
                for p in base.glob("bundle/app/blocks/*.py")
                if p.stem != "__init__"
            }
            found |= {
                p.stem
                for p in base.glob("app/blocks/*.py")
                if p.stem != "__init__"
            }
            found |= {
                d.name
                for d in base.glob("wave*/*")
                if d.is_dir() and (d / "code.py").is_file()
            }
            return found

        undeclared = {}
        for kit in client.get("/store/containers").json()["containers"]:
            allowed = known | _shipped_by(kit["id"])
            unknown = [b for b in kit.get("blocks", []) if b not in allowed]
            if unknown:
                undeclared[kit["id"]] = unknown

        assert not undeclared, (
            f"kits advertise blocks that are declared nowhere: {undeclared}"
        )


class TestWorkflowTriggersAPI:
    def test_list_builtin_triggers(self, client):
        response = client.get("/v1/workflows/triggers")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        trigger_ids = [t["trigger_id"] for t in data["triggers"]]
        assert "builtin-video-anomaly" in trigger_ids

    def test_register_custom_trigger(self, client):
        response = client.post(
            "/v1/workflows/triggers",
            json={
                "event_type": "video.anomaly",
                "min_severity": "critical",
                "description": "test trigger",
                "steps": [
                    {
                        "block_id": "video_anomaly_trigger",
                        "params": {"action": "evaluate"},
                        "input_mapping": {"metadata": "metadata"},
                    }
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "registered"
        assert data["trigger"]["event_type"] == "video.anomaly"
