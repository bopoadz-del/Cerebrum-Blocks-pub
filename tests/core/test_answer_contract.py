"""KERNEL_DEFAULTS K2 / K3, enforced on the contract itself.

These tests gate CI. Lane 2's table reports the same two claims
store-wide and is REPORT-ONLY; a red here is this module's own defect.
"""

from __future__ import annotations

import pytest

from app.core.answer_contract import (
    SOURCE_CLASS_KEY,
    AnswerContractViolation,
    apply_answer_contract,
    claims_does_not_exist,
    coverage_fraction,
    coverage_line,
    emit_chunk,
    forbid_does_not_exist_claim,
    is_fully_indexed,
    render_citations,
    render_source_class,
    source_class_of,
)


def _chunk(text="Paris is the capital of France.", classified="official_guidance", **extra):
    payload = {
        "id": extra.pop("id", "c1"),
        "text": text,
        "metadata": {SOURCE_CLASS_KEY: classified, **extra.pop("metadata", {})},
    }
    payload.update(extra)
    return payload


# -- K2: source-class rendering -------------------------------------------


def test_a_chunk_emits_its_class_at_the_top_level():
    emitted = emit_chunk(_chunk())
    assert emitted[SOURCE_CLASS_KEY] == "official_guidance"
    assert emitted["metadata"][SOURCE_CLASS_KEY] == "official_guidance"


def test_class_is_read_from_metadata_when_not_on_the_chunk():
    assert source_class_of({"metadata": {SOURCE_CLASS_KEY: "regulator"}}) == "regulator"


def test_a_chunk_with_no_class_cannot_be_emitted():
    with pytest.raises(AnswerContractViolation) as excinfo:
        emit_chunk({"id": "c1", "text": "no class here"})
    assert SOURCE_CLASS_KEY in str(excinfo.value)


def test_an_empty_class_is_not_a_class():
    with pytest.raises(AnswerContractViolation):
        emit_chunk({"id": "c1", SOURCE_CLASS_KEY: "   "})


def test_the_answer_layer_renders_the_class():
    line = render_source_class(_chunk(classified="regulator"))
    assert line == "source_class: regulator"


def test_every_citation_carries_a_rendered_class():
    citations = render_citations(
        [
            _chunk(id="c1", classified="regulator"),
            _chunk(id="c2", classified="contributor_unverified"),
        ]
    )
    assert [c[SOURCE_CLASS_KEY] for c in citations] == [
        "regulator",
        "contributor_unverified",
    ]
    assert all("source_class:" in c["source_class_line"] for c in citations)


def test_one_unclassified_chunk_fails_the_whole_citation_list():
    with pytest.raises(AnswerContractViolation):
        render_citations([_chunk(), {"id": "bare", "text": "no class"}])


# -- K3: coverage honesty -------------------------------------------------


def test_the_coverage_line_is_n_of_m_indexed():
    assert coverage_line(3, 10) == "3 of 10 indexed"
    assert coverage_line(10, 10) == "10 of 10 indexed"


def test_coverage_fraction_is_none_when_the_corpus_is_empty():
    """Zero total is not 0% and not 100%. It is unmeasurable."""
    assert coverage_fraction(0, 0) is None
    assert coverage_fraction(3, 10) == pytest.approx(0.3)


def test_indexed_cannot_exceed_total():
    with pytest.raises(AnswerContractViolation):
        coverage_line(11, 10)


@pytest.mark.parametrize("bad", [-1, True, 1.5, "3"])
def test_coverage_counts_must_be_honest_ints(bad):
    with pytest.raises(AnswerContractViolation):
        coverage_line(bad, 10)  # type: ignore[arg-type]


def test_full_coverage_is_only_n_equals_m_on_a_known_corpus():
    assert is_fully_indexed(10, 10) is True
    assert is_fully_indexed(9, 10) is False
    assert is_fully_indexed(10, None) is False
    assert is_fully_indexed(0, 0) is False


def test_does_not_exist_is_detected_in_both_spellings():
    assert claims_does_not_exist("that rate does-not-exist in the corpus")
    assert claims_does_not_exist("That document does not exist.")
    assert not claims_does_not_exist("I could not confirm this in the indexed sources.")


def test_does_not_exist_is_prohibited_below_full_coverage():
    with pytest.raises(AnswerContractViolation) as excinfo:
        forbid_does_not_exist_claim(
            "the 2026 rate table does-not-exist", indexed=3, total=10
        )
    assert "100 percent" in str(excinfo.value)


def test_does_not_exist_is_prohibited_when_coverage_cannot_be_measured():
    """Unknown M is not 100%. The negative claim is still forbidden."""
    with pytest.raises(AnswerContractViolation):
        forbid_does_not_exist_claim(
            "this clause does not exist", indexed=4, total=None
        )


def test_does_not_exist_is_allowed_only_at_100_percent():
    text = "the 2019 rate table does-not-exist in this corpus"
    assert forbid_does_not_exist_claim(text, indexed=10, total=10) == text


def test_an_answer_that_does_not_claim_absence_is_fine_on_a_partial_index():
    text = "I could not confirm this in the indexed sources."
    assert forbid_does_not_exist_claim(text, indexed=3, total=10) == text


# -- the composed payload -------------------------------------------------


def test_apply_answer_contract_renders_class_and_coverage():
    payload = apply_answer_contract(
        chunks=[_chunk()],
        answer_text="Paris is the capital of France. [Source 1]",
        indexed=3,
        total=10,
    )
    assert payload["coverage_line"] == "3 of 10 indexed"
    assert payload["coverage"] == pytest.approx(0.3)
    assert payload["citations"][0][SOURCE_CLASS_KEY] == "official_guidance"
    assert payload["source_class_rendered"] is True


def test_apply_answer_contract_refuses_a_does_not_exist_on_a_partial_index():
    with pytest.raises(AnswerContractViolation):
        apply_answer_contract(
            chunks=[_chunk()],
            answer_text="that clause does-not-exist",
            indexed=3,
            total=10,
        )
