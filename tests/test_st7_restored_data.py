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


# --- served skill text: no hosting-provider names, no angle-bracket placeholders ---
import re  # noqa: E402

PROVIDER = re.compile(r"\b(aws|render|heroku|vercel|netlify|azure)\b", re.IGNORECASE)
PLACEHOLDER = re.compile(r"<[a-z][a-z0-9-]*>")


def served_text_hits(text: str) -> list:
    """(line, kind, match) for provider names and <placeholder> tokens."""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        hits += [(i, "provider", m.group(0)) for m in PROVIDER.finditer(line)]
        hits += [(i, "placeholder", m.group(0)) for m in PLACEHOLDER.finditer(line)]
    return hits


def test_served_skill_text_is_provider_neutral_and_placeholder_free():
    assert served_text_hits((ROOT / "data/CEREBRUM_SKILL.md").read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("text, expected", [
    ("# Then: the deploy workflow ships the pushed commit\n", []),
    ("# Then: the deploy workflow (deploy-aws) ships the pushed commit\n", [(1, "provider", "aws")]),
    ("ok\nDeploy on Render.\n", [(2, "provider", "Render")]),
    ("git pull origin main\n", []),
    ("git clone <store-repo-url>\n", [(1, "placeholder", "<store-repo-url>")]),
    ("awsome lambda rendering\n", []),
])
def test_served_text_hits_two_inputs(text, expected):
    assert served_text_hits(text) == expected
