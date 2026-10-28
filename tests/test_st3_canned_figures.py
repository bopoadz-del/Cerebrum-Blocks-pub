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


def _row(factor, publication="Test Index 2026, table 3", evidence_class="A"):
    return {"factor": factor, "source": {"publication": publication, "evidence_class": evidence_class}}


def test_no_unsourced_factor_table_ships():
    assert not (KNOWLEDGE / "location_factors.json").exists()
    from app.blocks import historical_benchmark as hb

    assert not hasattr(hb, "_LOCATION_FACTORS") and not hasattr(hb, "_DEFAULT_LOCATION_FACTORS_PATH")


@pytest.mark.parametrize("place", ["Dubai", "London"])
def test_without_a_configured_table_no_figure_is_given(place):
    out = _lookup({}, place)
    assert out["status"] == "no_location_factor"
    assert "no location factor table is configured" in out["reason"]
    assert "rates" not in out and "adjusted_usd" not in json.dumps(out)


@pytest.mark.parametrize("place,factor", [("Atlantis", 0.5), ("North Pole", 2.25)])
def test_sourced_factors_come_from_the_data_file_with_their_source(tmp_path, place, factor):
    path = _write(tmp_path, "f.json", {"source": {"origin": f"test index {place}"},
                                       "factors": {place: _row(factor, f"pub {place}")}})
    out = _lookup({"location_factors_path": str(path)}, place)
    assert out["status"] == "success"
    f = out["factors"]
    assert f["location_factor"] == factor
    assert f["location_factor_source"]["origin"] == f"test index {place}"
    assert f["location_factor_source"]["publication"] == f"pub {place}"
    assert out["rates"]["adjusted_usd"] == round(out["rates"]["base_usd"] * factor, 2)


@pytest.mark.parametrize("cls", ["A", "unverified"])
def test_the_row_evidence_class_is_carried_into_the_surfaced_source(tmp_path, cls):
    path = _write(tmp_path, "f.json", {"source": {"origin": "o"}, "factors": {"x": _row(1.2, evidence_class=cls)}})
    out = _lookup({"location_factors_path": str(path)}, "x")
    assert out["factors"]["location_factor_source"]["evidence_class"] == cls


@pytest.mark.parametrize("row", [1.4, {"factor": 1.4}, {"factor": 1.4, "source": {}},
                                 {"factor": 1.4, "source": {"publication": "  "}}])
def test_a_row_without_a_published_source_gives_no_figure(tmp_path, row):
    path = _write(tmp_path, "f.json", {"source": {"origin": "o"},
                                       "factors": {"dubai": row, "elsewhere": _row(3.0)}})
    out = _lookup({"location_factors_path": str(path)}, "Dubai")
    assert out["status"] == "no_location_factor"
    assert "names no published source" in out["reason"]
    assert "rates" not in out
    assert _lookup({"location_factors_path": str(path)}, "elsewhere")["status"] == "success"


@pytest.mark.parametrize("place", ["Atlantis", "Nowhere"])
def test_an_unlisted_location_is_no_location_factor_not_priced(tmp_path, place):
    path = _write(tmp_path, "f.json", {"source": {"origin": "x"}, "factors": {"elsewhere": _row(3.0)}})
    out = _lookup({"location_factors_path": str(path)}, place)
    assert out["status"] == "no_location_factor"
    assert "rates" not in out and "adjusted_usd" not in json.dumps(out)
    assert place in out["reason"] and "not listed" in out["reason"]


@pytest.mark.parametrize("doc,msg", [
    ({"source": {"origin": "o"}, "factors": {}}, "missing or empty"),
    ({"source": {"origin": "o"}}, "missing or empty"),
    ({"source": {"origin": "o"}, "factors": {"a": _row(-1)}}, "finite positive"),
    ({"source": {"origin": "o"}, "factors": {"a": _row(0)}}, "finite positive"),
    ({"source": {"origin": "o"}, "factors": {"a": _row("nan")}}, "finite positive"),
    ({"source": {"origin": "o"}, "factors": {"a": _row("inf")}}, "finite positive"),
    ({"source": {"origin": "o"}, "factors": {"a": _row("cheap")}}, "not a number"),
])
def test_bad_factor_tables_are_refused(tmp_path, doc, msg):
    from app.blocks.historical_benchmark import load_location_factors

    p = _write(tmp_path, "f.json", doc)
    with pytest.raises(ValueError, match=msg):
        load_location_factors(p)
    out = _lookup({"location_factors_path": str(p)}, "a")
    assert out["status"] == "error" and "location factors unavailable" in out["error"]


@pytest.mark.parametrize("doc", [{"factors": {"a": _row(1.1)}}, {"source": {}, "factors": {"a": _row(1.1)}}])
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
    ({"source": {"origin": "o"}, "demo_markets": "uae"}, "must be a list"),
    ({"source": {"origin": "o"}, "demo_markets": ["a"], "unsupported_markets": "ksa"}, "must be a list"),
    ({"source": {"origin": "o"}, "demo_markets": ["a", ""]}, "blank or non-string"),
    ({"source": {"origin": "o"}, "demo_markets": ["a", "  "]}, "blank or non-string"),
    ({"source": {"origin": "o"}, "demo_markets": ["a", 7]}, "blank or non-string"),
])
def test_bad_market_files_are_refused(tmp_path, doc, msg):
    from app.blocks.ppm_licensing_resolver import load_markets

    with pytest.raises(ValueError, match=msg):
        load_markets(_write(tmp_path, "m.json", doc))


def test_the_guard_reads_a_substituted_markets_file(tmp_path):
    from app.blocks.ppm_licensing_resolver import GuardError, guard_request

    p = _write(tmp_path, "m.json", {"source": {"origin": "o"}, "demo_markets": ["zz"],
                                    "unsupported_markets": ["uae"]})
    guard_request(market="zz", markets_path=p, demo_only=True)
    with pytest.raises(GuardError) as e:
        guard_request(market="uae", markets_path=p)
    assert e.value.code == "market_unsupported"
    # the shipped file says the opposite, so the outcome is the file's, not a literal's
    guard_request(market="uae")
    with pytest.raises(GuardError):
        guard_request(market="zz")


def _scope_file(tmp_path, **over):
    doc = {"source": {"origin": "o"}, "demo_markets": ["atl", "atl_city", "generic"],
           "unsupported_markets": ["mu"],
           "market_aliases": {"atl_city": "atl", "mu": "mu"},
           "market_labels": {"atl": "Atlantis", "mu": "Mu", "generic": "generic"},
           "market_packs": {"atl": {"licensing": "LICENSING_UAE", "prerequisites": "PREREQ_UAE", "ppm": "PPM_UAE"}}}
    doc.update(over)
    return _write(tmp_path, "m.json", doc)


@pytest.mark.parametrize("allowed,refused", [("zz", "uae"), ("uae", "zz")])
def test_the_default_guard_reads_markets_path_not_literals(tmp_path, monkeypatch, allowed, refused):
    from app.blocks import ppm_licensing_resolver as ppm

    p = _write(tmp_path, "m.json", {"source": {"origin": "o"}, "demo_markets": [allowed],
                                    "unsupported_markets": [refused]})
    monkeypatch.setattr(ppm, "MARKETS_PATH", p)
    ppm.guard_request(market=allowed)
    with pytest.raises(ppm.GuardError) as e:
        ppm.guard_request(market=refused)
    assert e.value.code == "market_unsupported"


def test_guard_messages_are_generated_from_the_market_data(tmp_path):
    from app.blocks.ppm_licensing_resolver import GuardError, guard_request

    p = _scope_file(tmp_path)
    with pytest.raises(GuardError) as e:
        guard_request(market="mu", markets_path=p)
    assert e.value.message == "Mu is unsupported and stripped. Supported markets: Atlantis and generic only."
    with pytest.raises(GuardError) as e:
        guard_request(market="uae", markets_path=p)
    assert e.value.message == "Supported markets: Atlantis and generic only."
    with pytest.raises(GuardError) as e:
        guard_request(market="zz", markets_path=p, demo_only=True)
    assert (e.value.code, e.value.message) == ("market_not_demo_geography", "Pilot demo fixtures are Atlantis + generic only.")
    with pytest.raises(GuardError) as e:
        guard_request(market="ksa")
    assert e.value.message == "KSA is unsupported and stripped. Supported markets: UAE and generic only."


def test_router_aliases_and_packs_come_from_the_market_data(tmp_path):
    from app.blocks.ppm_licensing_resolver import (
        GuardError, LICENSING_GENERIC, LICENSING_UAE, PPM_UAE, MarketRouter, load_market_scope)

    router = MarketRouter(load_market_scope(_scope_file(tmp_path)))
    assert router.normalize("atl_city") == "atl" and router.normalize("generic") == "generic"
    with pytest.raises(GuardError):
        router.normalize("dubai")
    assert router.licensing_pack("atl_city")["licenses"] == LICENSING_UAE["licenses"]
    assert router.ppm_pack("atl") is PPM_UAE
    assert router.licensing_pack("generic")["licenses"] == LICENSING_GENERIC["licenses"]
    # the shipped data maps the emirates to the UAE pack
    shipped = MarketRouter()
    assert shipped.normalize("Sharjah") == "uae" and shipped.ppm_pack("dubai") is PPM_UAE
    assert shipped.ppm_pack("generic") is not PPM_UAE


def test_a_pack_name_the_code_does_not_load_is_refused(tmp_path):
    from app.blocks.ppm_licensing_resolver import GuardError, MarketRouter, load_market_scope

    p = _scope_file(tmp_path, market_packs={"atl": {"ppm": "PPM_NOWHERE"}})
    with pytest.raises(GuardError) as e:
        MarketRouter(load_market_scope(p)).ppm_pack("atl")
    assert e.value.code == "market_pack_missing"


def test_resolver_source_has_no_emirate_list_or_uae_branch():
    text = (ROOT / "app/blocks/ppm_licensing_resolver.py").read_text(encoding="utf-8")
    assert '== "uae"' not in text and '"sharjah"' not in text and '"ajman"' not in text
    assert "KSA is unsupported" not in text and "UAE and generic only" not in text


# -- one generic publisher -------------------------------------------------------------------


def test_finance_ops_is_published_by_the_generic_publisher():
    manifest = json.loads((ROOT / "block_store/kits/finance_ops/manifest.json").read_text(encoding="utf-8"))
    script = manifest["source"]["publish_script"]
    assert script == "scripts/publish_kit.py"
    assert not (ROOT / "scripts" / "publish_finance_ops_kit.py").exists()
    run = subprocess.run([sys.executable, str(ROOT / script), "--domain", "finance_ops", "--check"],
                         capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize("slug", ["acme/widgets", "someone-else/fork"])
def test_publisher_identity_comes_from_the_repository_not_a_literal(slug):
    sys.path.insert(0, str(ROOT / "scripts"))
    import publish_kit

    ident = publish_kit.repo_identity({"GITHUB_REPOSITORY": slug})
    assert ident == {"owner": slug.split("/")[0], "repo": f"https://github.com/{slug}"}
    m = publish_kit._build_manifest("finance_ops", ident)
    assert m["author"] == slug.split("/")[0] and m["source"]["repo"] == ident["repo"]


def _git_checkout(tmp_path, name, origin):
    d = tmp_path / name
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    if origin:
        subprocess.run(["git", "remote", "add", "origin", origin], cwd=d, check=True)
    return d


@pytest.mark.parametrize("origin,slug", [
    ("https://github.com/acme/widgets.git", "acme/widgets"),
    ("git@github.com:someone-else/fork", "someone-else/fork"),
])
def test_repo_identity_parses_the_git_origin(tmp_path, origin, slug):
    sys.path.insert(0, str(ROOT / "scripts"))
    import publish_kit

    ident = publish_kit.repo_identity({}, checkout=_git_checkout(tmp_path, "c", origin))
    assert ident == {"owner": slug.split("/")[0], "repo": f"https://github.com/{slug}"}


@pytest.mark.parametrize("origin", [None, "https://gitlab.example/acme/widgets.git"])
def test_repo_identity_raises_without_env_or_github_origin(tmp_path, origin):
    sys.path.insert(0, str(ROOT / "scripts"))
    import publish_kit

    with pytest.raises(RuntimeError, match="cannot determine the repository owner"):
        publish_kit.repo_identity({}, checkout=_git_checkout(tmp_path, "c", origin))


@pytest.mark.parametrize("slug", ["acme/widgets", "someone-else/fork"])
def test_stamp_identity_regenerates_author_and_repo(tmp_path, slug):
    sys.path.insert(0, str(ROOT / "scripts"))
    import publish_kit

    m = tmp_path / "manifest.json"
    m.write_text((ROOT / "block_store/kits/finance_ops/manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
    out = publish_kit.stamp_identity(m, publish_kit.repo_identity({"GITHUB_REPOSITORY": slug}))
    on_disk = json.loads(m.read_text(encoding="utf-8"))
    assert on_disk == out
    assert on_disk["author"] == slug.split("/")[0]
    assert on_disk["source"]["repo"] == f"https://github.com/{slug}"
    assert on_disk["source"]["publish_script"] == "scripts/publish_kit.py"


def test_publisher_carries_no_owner_handle_and_manifest_matches_the_repo():
    text = (ROOT / "scripts/publish_kit.py").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "block_store/kits/finance_ops/manifest.json").read_text(encoding="utf-8"))
    assert '"author": "' not in text and "github.com/" + manifest["author"] not in text
    assert manifest["source"]["repo"] == "https://github.com/" + manifest["author"] + "/Cerebrum-Blocks-pub"
