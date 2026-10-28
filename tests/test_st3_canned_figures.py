"""ST-3 (ORDERS 0815Z B5): canned figures become data inputs with a source,
and per-product publish scripts give way to the generic publisher."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "app" / "knowledge"


def _write(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


# -- historical_benchmark location factors ---------------------------------------------------


def _lookup(config, location):
    from app.blocks.historical_benchmark import HistoricalBenchmarkBlock

    block = HistoricalBenchmarkBlock(config=config)
    return asyncio.run(block.process({"item": "concrete", "location": location}, {}))


def test_the_shipped_location_factors_carry_a_source():
    doc = json.loads((KNOWLEDGE / "location_factors.json").read_text(encoding="utf-8"))
    assert doc["source"]["origin"] and doc["source"]["evidence_class"]
    assert doc["factors"]


@pytest.mark.parametrize("place,factor", [("Atlantis", 0.5), ("North Pole", 2.25)])
def test_factors_come_from_the_data_file_with_its_source(tmp_path, place, factor):
    path = _write(tmp_path, "f.json", {"source": {"origin": f"test index {place}"},
                                       "factors": {place: factor}})
    out = _lookup({"location_factors_path": str(path)}, place)
    assert out["status"] == "success"
    f = out["factors"]
    assert f["location_factor"] == factor and f["location_factor_matched"] is True
    assert f["location_factor_source"]["origin"] == f"test index {place}"
    assert out["rates"]["adjusted_usd"] == round(out["rates"]["base_usd"] * factor, 2)


@pytest.mark.parametrize("place", ["Atlantis", "Nowhere"])
def test_an_unlisted_location_is_flagged_not_passed_off(tmp_path, place):
    path = _write(tmp_path, "f.json", {"source": {"origin": "x"}, "factors": {"elsewhere": 3.0}})
    f = _lookup({"location_factors_path": str(path)}, place)["factors"]
    assert f["location_factor"] == 1.0 and f["location_factor_matched"] is False


@pytest.mark.parametrize("doc", [{"factors": {"a": 1.1}}, {"source": {}, "factors": {"a": 1.1}}])
def test_sourceless_factors_are_refused(tmp_path, doc):
    out = _lookup({"location_factors_path": str(_write(tmp_path, "f.json", doc))}, "a")
    assert out["status"] == "error" and "no source record" in out["error"]


def test_a_missing_factor_file_is_refused(tmp_path):
    out = _lookup({"location_factors_path": str(tmp_path / "absent.json")}, "a")
    assert out["status"] == "error" and "location factors unavailable" in out["error"]


# -- ppm_licensing_resolver markets ----------------------------------------------------------


def test_the_shipped_market_sets_carry_a_source_and_drive_the_guard():
    from app.blocks import ppm_licensing_resolver as ppm

    doc = json.loads((KNOWLEDGE / "ppm_markets.json").read_text(encoding="utf-8"))
    assert doc["source"]["origin"]
    assert ppm.DEMO_MARKETS == set(doc["demo_markets"])
    assert ppm.UNSUPPORTED_MARKETS == set(doc["unsupported_markets"])
    assert ppm.MARKETS_SOURCE["origin"] == doc["source"]["origin"]


@pytest.mark.parametrize("demo,unsupported", [(["m1", "m2"], ["m9"]), (["zz"], [])])
def test_market_sets_load_from_any_file(tmp_path, demo, unsupported):
    from app.blocks.ppm_licensing_resolver import load_markets

    p = _write(tmp_path, "m.json", {"source": {"origin": "o"}, "demo_markets": demo,
                                    "unsupported_markets": unsupported})
    d, u, src = load_markets(p)
    assert d == set(demo) and u == set(unsupported) and src["origin"] == "o"


@pytest.mark.parametrize("doc,msg", [
    ({"demo_markets": ["a"]}, "no source record"),
    ({"source": {"origin": "o"}, "demo_markets": []}, "no demo markets"),
    ({"source": {"origin": "o"}, "demo_markets": ["a"], "unsupported_markets": ["a"]}, "both demo and unsupported"),
])
def test_bad_market_files_are_refused(tmp_path, doc, msg):
    from app.blocks.ppm_licensing_resolver import load_markets

    with pytest.raises(ValueError, match=msg):
        load_markets(_write(tmp_path, "m.json", doc))


# -- one generic publisher -------------------------------------------------------------------


def test_finance_ops_is_published_by_the_generic_publisher():
    manifest = json.loads((ROOT / "block_store/kits/finance_ops/manifest.json").read_text(encoding="utf-8"))
    script = manifest["source"]["publish_script"]
    assert script == "scripts/publish_kit.py"
    assert not (ROOT / "scripts" / "publish_finance_ops_kit.py").exists()
    run = subprocess.run([sys.executable, str(ROOT / script), "--domain", "finance_ops", "--check"],
                         capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
