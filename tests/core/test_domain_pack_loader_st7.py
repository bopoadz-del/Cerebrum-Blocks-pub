"""ST-7: marketplace_ops / construction_ops / equipment_maintenance load
through the real loader. marketplace_ops shipped with a UTF-8 BOM that
loader.load_path (read_text utf-8 + json.loads) cannot parse."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.reasoning_kernel.loader import DomainPackLoader, PackLoadError

PACKS = Path(__file__).resolve().parents[2] / "domain_packs"
BOM = b"\xef\xbb\xbf"


@pytest.mark.parametrize("domain", ["marketplace_ops", "construction_ops", "equipment_maintenance"])
def test_pack_loads_and_matches_its_source(domain):
    path = PACKS / domain / "pack.json"
    raw = json.loads(path.read_bytes().decode("utf-8-sig"))
    pack = DomainPackLoader().load_path(str(path))
    assert pack.manifest.domain_id == raw["manifest"]["domain_id"] == domain
    assert [f.formula_id for f in pack.formulas] == [f["formula_id"] for f in raw["formulas"]]


def test_no_domain_pack_starts_with_a_bom():
    assert [p.parent.name for p in sorted(PACKS.glob("*/pack.json")) if p.read_bytes().startswith(BOM)] == []


@pytest.mark.parametrize("domain", ["marketplace_ops", "construction_ops"])
def test_bom_prefixed_copy_is_refused_and_clean_copy_loads(tmp_path, domain):
    body = (PACKS / domain / "pack.json").read_bytes()
    clean, bommed = tmp_path / "clean.json", tmp_path / "bom.json"
    clean.write_bytes(body)
    bommed.write_bytes(BOM + body)
    assert DomainPackLoader().load_path(str(clean)).manifest.domain_id == domain
    with pytest.raises(PackLoadError):
        DomainPackLoader().load_path(str(bommed))
