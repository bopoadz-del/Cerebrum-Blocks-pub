"""ST-7: the restored source files are what the readers load (not the silent {} / "")."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.core.construction_knowledge as ck
from app.blocks.skills import SkillsBlock

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("prc", ["PRC-501", "PRC-606"])
def test_procedures_db_restored_and_keyed_on_prc_ids(monkeypatch, prc):
    monkeypatch.setattr(ck, "_procedures_db", None)
    src = json.loads((ROOT / "app/data/procedures/procedures_db.json").read_text(encoding="utf-8"))
    proc = ck.get_procedure(prc)
    assert proc is not None and proc == src["procedures"][prc]


def test_every_critical_rule_procedure_resolves(monkeypatch):
    monkeypatch.setattr(ck, "_procedures_db", None)
    ids = {i for r in ck.CRITICAL_RULES.values() if "procedure" in r for i in r["procedure"].split("/")}
    assert ids and [i for i in sorted(ids) if ck.get_procedure(i) is None] == []


def test_skill_file_restored_and_parsed():
    block = SkillsBlock()
    text = (ROOT / "data/CEREBRUM_SKILL.md").read_text(encoding="utf-8")
    assert block._raw_content == text
    assert len(block._sections) >= 2
