"""model_clone: three tests + mutation probe.

The invariant under test is the one that decides whether an engineer can
accept this tool at all: the model of record is never written.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from app.blocks.ifc_loader import model_sha256
from app.blocks.model_clone import (
    BACKEND_IFC_COPY,
    apply_to_clone,
    speckle_available,
    write_change_set,
)


@dataclass
class P:
    clash_id: str = "C1"
    element: str = "GID-A"
    move_vector_mm: tuple = (325.0, 0.0, 0.0)
    status: str = "proposed"
    rule_ids: list = field(default_factory=lambda: ["MEP-GAS-ANY-300"])
    clause_text: str | None = "NOTES item 6: 300MM IN ANY DIRECTION"
    note: str | None = None


@pytest.fixture
def fake_ifc(tmp_path):
    """A real file on disk with real bytes. Not a mock: the whole point is
    hashing an actual file before and after."""
    p = tmp_path / "model.ifc"
    p.write_text("ISO-10303-21;\nHEADER;\nFILE_NAME('model.ifc');\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n")
    return p


def test_the_original_model_is_byte_identical_after_a_full_run(fake_ifc, tmp_path):
    """THE invariant. Everything else in this block is convenience."""
    before = model_sha256(fake_ifc)
    result = apply_to_clone(fake_ifc, [P(), P(clash_id="C2")], tmp_path / "out")
    after = model_sha256(fake_ifc)

    assert before == after
    assert result.original_untouched is True
    assert result.original_sha_before == result.original_sha_after
    # And the clone really is a separate file that exists.
    assert result.clone_path is not None
    assert str(fake_ifc) != result.clone_path


def test_the_change_set_carries_the_clause_and_separates_unsourced_entries(tmp_path):
    """An entry either names the rule that authorises it, or its status says
    it is not authorised. Never neither — that is how an unsourced number gets
    applied to a building."""
    proposals = [
        P(clash_id="C1"),
        P(clash_id="C2", status="flagged_unsourced", rule_ids=[], clause_text=None),
    ]
    path = write_change_set(proposals, tmp_path / "cs.json")
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["counts"]["proposed"] == 1
    assert data["counts"]["flagged_unsourced"] == 1
    sourced = [e for e in data["entries"] if e["status"] == "proposed"][0]
    assert sourced["rule_ids"] == ["MEP-GAS-ANY-300"]
    assert "300MM" in sourced["clause_text"]
    unsourced = [e for e in data["entries"] if e["status"] == "flagged_unsourced"][0]
    assert unsourced["rule_ids"] == []


def test_speckle_absence_falls_back_and_says_so_rather_than_pretending(fake_ifc, tmp_path):
    """A missing optional backend must be visible. Silently producing a copy
    and calling it a stream is how an operator discovers, weeks later, that no
    versioning ever existed."""
    available, reason = speckle_available()
    result = apply_to_clone(fake_ifc, [P()], tmp_path / "out")

    if not available:
        assert result.backend == BACKEND_IFC_COPY
        assert result.blocked is not None
        assert "BLOCKED(model_clone.speckle" in result.blocked
        assert "unblocker=" in result.blocked
        assert reason is not None
    else:
        assert result.speckle_stream is not None


def test_mutation_probe_writing_the_original_is_caught_and_raises(fake_ifc, tmp_path, monkeypatch):
    """MUTATION PROBE.

    The hash comparison is the guard. Simulate the failure it exists to catch —
    something modifying the original mid-run — and assert the block refuses
    loudly rather than returning a result that claims success.
    """
    import app.blocks.model_clone as mc

    real_annotate = mc._annotate_clone

    def sabotage(clone_path, proposals):
        real_annotate(clone_path, proposals)
        fake_ifc.write_text("MODIFIED BY A BUG\n")   # the thing that must never happen

    monkeypatch.setattr(mc, "_annotate_clone", sabotage)

    with pytest.raises(RuntimeError, match="modified the ORIGINAL model"):
        apply_to_clone(fake_ifc, [P()], tmp_path / "out")
