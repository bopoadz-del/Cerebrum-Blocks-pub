"""ST-7: the restored source files are what the readers load (not the silent {} / "")."""
from __future__ import annotations

import json
import re
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


# --- skill-file pin. The served-text detector itself (one case per
# alternative, boundary cases) is owned by #16 (tests/test_served_text_detector.py);
# this pin only checks that the shipped skill file stays clean, and that the
# check fails on a dirty copy.

_SERVED_OFFENCE = re.compile(r"\b(?:aws|render|heroku|vercel|netlify|azure)\b|<[a-z][a-z0-9-]*>", re.IGNORECASE)


def skill_file_offences(path: Path) -> list:
    return [m.group(0) for m in _SERVED_OFFENCE.finditer(path.read_text(encoding="utf-8"))]


def test_served_skill_file_is_provider_neutral_and_placeholder_free():
    assert skill_file_offences(ROOT / "data/CEREBRUM_SKILL.md") == []


@pytest.mark.parametrize("dirt, expected", [
    ("\nDeploy it on Render.\n", ["Render"]),
    ("\ngit clone <store-repo-url>\n", ["<store-repo-url>"]),
])
def test_skill_file_pin_goes_red_on_a_dirty_copy(tmp_path, dirt, expected):
    copy = tmp_path / "CEREBRUM_SKILL.md"
    copy.write_text((ROOT / "data/CEREBRUM_SKILL.md").read_text(encoding="utf-8") + dirt, encoding="utf-8")
    assert skill_file_offences(copy) == expected
