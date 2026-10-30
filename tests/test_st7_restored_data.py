"""ST-7: the restored source files are what the readers load (not the silent {} / "")."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.core.construction_knowledge as ck
from app.blocks.skills import SkillsBlock
from tests.test_served_text_detector import served_text_hits

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


# --- skill-file pin. The served-text detector is owned by #16
# (tests/test_served_text_detector.py) and is IMPORTED here, not copied, so
# any change to a detector rule moves this pin too. The pin checks that the
# shipped skill file stays clean, and that it goes red on a dirty copy: one
# dirty input per detector rule. Each dirty line carries the rule's near-miss
# beside the true hit, and the full hit list is compared, so a loosened rule
# adds an extra hit and a dropped rule loses the expected one.

SKILL = ROOT / "data/CEREBRUM_SKILL.md"


def skill_file_offences(path: Path) -> list:
    return [match for _line, _kind, match in served_text_hits(path.read_text(encoding="utf-8"))]


def test_served_skill_file_is_provider_neutral_and_placeholder_free():
    assert skill_file_offences(SKILL) == []


@pytest.mark.parametrize("rule, dirt, expected", [
    ("R1lead", "\njaws ship on aws\n", ["aws"]),
    ("R2trail", "\nawsome builds on aws\n", ["aws"]),
    ("A_render", "\nDeploy it on Render.\n", ["Render"]),
    ("A_aws", "\nDeploy it on AWS.\n", ["AWS"]),
    ("A_heroku", "\nPush it to Heroku.\n", ["Heroku"]),
    ("A_vercel", "\nRun vercel deploy.\n", ["vercel"]),
    ("A_netlify", "\nRun netlify build.\n", ["netlify"]),
    ("A_azure", "\nHost it on Azure.\n", ["Azure"]),
    ("P3first", "\ngit clone <-url> <store-repo-url>\n", ["<store-repo-url>"]),
    ("P5digit", "\nopen <port8080>\n", ["<port8080>"]),
    ("P6plus", "\nset <x>\n", ["<x>"]),
])
def test_skill_file_pin_goes_red_on_a_dirty_copy(tmp_path, rule, dirt, expected):
    copy = tmp_path / "CEREBRUM_SKILL.md"
    copy.write_text(SKILL.read_text(encoding="utf-8") + dirt, encoding="utf-8")
    assert skill_file_offences(copy) == expected, rule
