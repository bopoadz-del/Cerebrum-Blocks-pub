"""Wave 1.1 regression tests — document_engine ports from The_Fork.

Each test locks one of the survey's confirmed defects so a revert fails:

1. _map_wbs KeyError on trimmed client WBS dictionaries (crash fix).
2. Inline brief (text-only, no file) scope-extraction path.
3. raw_text passthrough — a BOQ-style upload must not degrade to
   generic ontology defaults with zero rows from the actual file.
"""

import asyncio

from app.blocks.document_engine.reasoner import DocumentReasoner
from app.blocks.document_engine_block import DocumentEngineBlock


def test_wbs_mapping_survives_trimmed_dictionary():
    """A client config whose wbs_dictionary lacks a category's target code
    must degrade to an extra mapping bucket, not raise KeyError and kill
    the whole reasoning pass."""
    reasoner = DocumentReasoner({"wbs_dictionary": {"1.0": "Scheduling"}})
    requirements = [
        {"text": "Provide electrical switchboards and distribution", "category": "electrical"},
        {"text": "Weekly progress reporting", "category": "schedule"},
    ]
    mapped = reasoner._map_wbs("some text", requirements, [])

    # "electrical" resolves to 7.0, which the trimmed dictionary lacks —
    # the bucket must still exist (setdefault path).
    assert "7.0" in mapped
    assert mapped["7.0"][0]["type"] == "requirement"
    assert mapped["7.0"][0]["category"] == "electrical"
    # The declared code still receives its own entries.
    assert "1.0" in mapped
    assert mapped["1.0"][0]["category"] == "schedule"


def test_constraint_mapping_survives_trimmed_dictionary():
    """Same guard for the constraint-unit mapping path."""
    reasoner = DocumentReasoner({"wbs_dictionary": {"1.0": "Scheduling"}})
    constraints = [
        {"raw": "clearance at least 10 ft", "unit": "ft", "value": "10"},
    ]
    mapped = reasoner._map_wbs("some text", [], constraints)
    # "ft" resolves to 5.0, absent from the trimmed dictionary — the
    # setdefault bucket must appear instead of a KeyError.
    assert "5.0" in mapped
    assert mapped["5.0"][0]["type"] == "constraint"


def test_inline_brief_path_and_raw_text_passthrough():
    """A raw non-path string is an inline brief: the pipeline reasons over
    it via a synthetic document, and the RAW text is surfaced in the
    result instead of only ontology defaults."""
    block = DocumentEngineBlock()
    brief = (
        "The client requires a 3-storey warehouse with electrical "
        "switchboards and a 14-month completion target."
    )
    out = asyncio.run(block.process(brief))

    assert out["status"] == "success", out.get("error")
    assert out["documents_parsed"] >= 1
    assert "warehouse" in out.get("raw_text", ""), (
        "raw_text must carry the actual brief content"
    )
    assert out.get("raw_text_truncated") is False


def test_no_input_still_errors_honestly():
    block = DocumentEngineBlock()
    out = asyncio.run(block.process({}))
    assert out["status"] == "error"
    assert "inline text" in out.get("error", "")
