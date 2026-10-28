"""ST-2 (ORDERS 0815Z B2/B6): placeholders become real code or computed
refusals. Each fix is driven with two different inputs."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "block_store" / "kits" / "_template" / "manifest.json"


def _script(name):
    spec = importlib.util.spec_from_file_location(f"st2_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -- kits/_template/manifest.json is valid JSON and still renders ---------------------------


def test_the_template_manifest_is_strict_json():
    json.loads(TEMPLATE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("tags", [["domain", "container", "alpha"], ["beta"]])
def test_both_renderers_turn_the_tags_placeholder_into_a_json_array(tags):
    text = TEMPLATE.read_text(encoding="utf-8")
    ctx = {"domain": "alpha", "Domain": "Alpha", "name": "A", "description": "d",
           "status": "draft", "tags_json": json.dumps(tags)}
    gen = _script("generate_domain_kit")
    assert json.loads(gen._render(text, ctx))["tags"] == tags
    scaffold = _script("scaffold_kit")
    assert json.loads(scaffold.substitute(text, ctx))["tags"] == tags


# -- publish_kit: "available" is derived from the kit's real files --------------------------


@pytest.mark.parametrize("domain", ["alpha_kit", "beta_kit"])
def test_publish_status_follows_the_files_on_disk(tmp_path, monkeypatch, domain):
    pk = _script("publish_kit")
    monkeypatch.setattr(pk, "PROJECT_ROOT", tmp_path)
    first = pk._build_manifest(domain)
    assert first["status"] == "in_development"
    for art in first["artifacts"]:
        p = tmp_path / art["src"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    assert pk._build_manifest(domain)["status"] == "available"
    (tmp_path / first["artifacts"][0]["src"]).unlink()
    assert pk._build_manifest(domain)["status"] == "in_development"


# -- migration: an unedited template refuses; a failed run is an error ----------------------


class _Host:
    """What a generated migration script is handed at run time."""

    def get_dependency(self, name):
        return object()


@pytest.mark.parametrize("name", ["add_index", "drop_column"])
def test_an_unedited_migration_template_refuses_and_the_run_is_an_error(name):
    from app.blocks.migration import MigrationBlock

    block = MigrationBlock(config={"backup_before_migrate": False})
    created = asyncio.run(block._create_migration_script({"name": name}))
    ns: dict = {}
    exec(created.get("template") or block.migrations[created["version"]]["template"], ns)
    with pytest.raises(NotImplementedError, match=name):
        asyncio.run(ns["up"](_Host()))
    with pytest.raises(NotImplementedError, match=name):
        asyncio.run(ns["down"](_Host()))
    block.migrations[created["version"]]["up"] = lambda _b: ns["up"](_Host())
    out = asyncio.run(block._run_migration({}))
    assert out["status"] == "error" and out["failed_version"] == created["version"]
    assert out["migrations_run"] == 0 and created["version"] not in block.applied_migrations


def test_a_clean_migration_run_is_a_success():
    from app.blocks.migration import MigrationBlock

    async def up(_):
        return {"ok": True}

    block = MigrationBlock(config={"backup_before_migrate": False})
    block.migrations["001"] = {"version": "001", "name": "n", "up": up}
    out = asyncio.run(block._run_migration({}))
    assert out["status"] == "success" and out["failed_version"] is None


# -- ocr: why tesseract was not used, and unread confidences, are stated --------------------


def _fake_tesseract(monkeypatch, *, version_error=None, data_error=None):
    mod = types.ModuleType("pytesseract")

    def get_tesseract_version():
        if version_error:
            raise version_error
        return "5"

    def image_to_data(*a, **k):
        if data_error:
            raise data_error
        return {"conf": ["90"]}

    mod.get_tesseract_version = get_tesseract_version
    mod.image_to_string = lambda *a, **k: "hello"
    mod.image_to_data = image_to_data
    mod.Output = types.SimpleNamespace(DICT="dict")
    monkeypatch.setitem(sys.modules, "pytesseract", mod)


def _ocr(monkeypatch, tmp_path):
    from PIL import Image
    from app.blocks.ocr import OCRBlock

    img = tmp_path / "p.png"
    Image.new("RGB", (8, 8), "white").save(img)
    block = OCRBlock()
    monkeypatch.setattr(block, "_prepare_images", lambda path, pre: [str(img)])
    monkeypatch.setattr(block, "_detect_markup", lambda path: {"has_markup": False})
    monkeypatch.setattr(block, "_extract_pdf_text", lambda path: "layer text")
    return block, str(img)


@pytest.mark.parametrize("err", [RuntimeError("tesseract is not installed"), OSError("no binary")])
def test_the_fallback_names_the_real_tesseract_failure(monkeypatch, tmp_path, err):
    _fake_tesseract(monkeypatch, version_error=err)
    block, img = _ocr(monkeypatch, tmp_path)
    out = asyncio.run(block._process_image(img, {}))
    assert out["engine"] == "pymupdf_fallback"
    assert type(err).__name__ in out["note"] and str(err) in out["note"]


@pytest.mark.parametrize("err", [ValueError("bad tsv"), RuntimeError("timeout")])
def test_an_unread_confidence_is_reported_not_swallowed(monkeypatch, tmp_path, err):
    _fake_tesseract(monkeypatch, data_error=err)
    block, img = _ocr(monkeypatch, tmp_path)
    out = asyncio.run(block._process_image(img, {}))
    assert out["text"] == "hello"
    errors = out["quality"]["confidence_errors"]
    assert len(errors) == 1 and str(err) in errors[0]


# -- review / discovery / error_tracking: state is stated -----------------------------------


def test_review_and_discovery_health_state_what_is_not_there():
    from app.blocks.discovery import DiscoveryBlock
    from app.blocks.review import ReviewBlock

    r = ReviewBlock().health()
    assert r["persistent"] is False and "in-memory" in r["storage"]
    d = DiscoveryBlock().health()
    assert d["usage_patterns_source"].startswith("not loaded")


@pytest.mark.parametrize("exc", [ValueError("boom"), KeyError("missing")])
def test_the_error_tracking_excepthook_captures_and_hands_on(monkeypatch, exc):
    from app.blocks.error_tracking import ErrorTrackingBlock

    seen = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: seen.append(a[0]))
    block = ErrorTrackingBlock(config={"install_excepthook": True})
    block._install_excepthook()
    assert block.excepthook_installed and block.health()["excepthook_installed"]
    sys.excepthook(type(exc), exc, None)
    assert seen == [type(exc)]
    assert any(type(exc).__name__ == (e.get("exception_type") or e.get("type") or e.get("exc_type"))
               or type(exc).__name__ in json.dumps(e, default=str) for e in block.events)


def test_error_tracking_installs_no_hook_unless_asked(monkeypatch):
    from app.blocks.error_tracking import ErrorTrackingBlock

    before = sys.excepthook
    block = ErrorTrackingBlock()
    assert block.config.get("install_excepthook") is False
    assert sys.excepthook is before
