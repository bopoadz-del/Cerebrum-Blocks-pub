"""Contract retrieval tests - ported behavior from The_Fork.

Fixtures are the donor's own sanitized corpus (tests/test_cross_contract_fence.py
and tests/test_unnamed_contract_year_lock.py): DD-2022-175 vs DD-2023-118.
What is under test is the mechanism - which contract's rows win - not live numbers.
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ENV", "test")

from app.blocks import contract_retrieval as m
from app.blocks.contract_retrieval import ContractRetrievalBlock

DD23_NAME = (
    "DD-2023-118_the client project II Infrastructure Package 1_"
    "Vol 1 - Conditions of Contract.pdf"
)
DD22_NAME = "DD-2022-175 - Volume 1 - Conditions of Contract.pdf"
DD22_SCHED_NAME = (
    "DD-2022-175 - the project Demolition and Site Clearance Works "
    "Package 1 Volume 4 Schedules.pdf"
)

A3 = "What is the Time for Completion for the whole of the Works?"
A5 = "What are the Delay Damages for the whole of the Works?"
LIVE_PREFIX = "Answer only from the client project documents. "
LIVE_A3 = LIVE_PREFIX + A3
LIVE_A5 = LIVE_PREFIX + A5

DD22_DELAY_CLAUSE = (
    "Volume 1 - Conditions of Contract. Sub-Clause 8.8 Delay Damages. If "
    "the Contractor fails to comply with Sub-Clause 8.2, the Contractor "
    "shall pay delay damages for the whole of the Works at the rate stated "
    "in the Contract Data for every calendar day which shall elapse between "
    "the relevant Time for Completion and the date stated in the Taking-Over "
    "Certificate, up to the maximum amount of delay damages stated in the "
    "Contract Data, being 10% of the Accepted Contract Amount."
)
DD23_UNSPLIT_TFC_LINE = (
    "1.1.75 Time for Completion for the whole of the Works 852 days"
)
DD23_UNSPLIT_DELAY_LINE = (
    "8.8 Delay Damages for the whole of the Works 0.1% of the "
    "Contract Price per calendar day"
)
DD22_SCHEDULE_548 = (
    "Schedule 5: Project Schedule. Overall duration for the completion "
    "of the Works is 548 days from the Commencement Date."
)
DD22_FILLED_TFC_548 = (
    "CONTRACT DATA particulars \u2014 filled-in amount / duration / "
    f"percentage [{DD22_NAME}].\n"
    "Particular Conditions Part A - Contract Data\n"
    "1.1.75 Time for Completion for the whole of the Works: 548 days"
)
DD22_FILLED_DELAY_CAP = (
    "CONTRACT DATA particulars \u2014 filled-in amount / duration / "
    f"percentage [{DD22_NAME}].\n"
    "Particular Conditions Part A - Contract Data\n"
    "8.8 Maximum amount of delay damages: 10% of the Accepted Contract Amount"
)


def _unsplit_particulars_chunk(line: str) -> str:
    return (
        "CONTRACT DATA particulars \u2014 filled-in amount / duration / "
        f"percentage [{DD23_NAME}].\n"
        "Particular Conditions Part A - Contract Data\n"
        f"{line}"
    )


def _ranked(*pairs):
    return list(pairs)


def _run(coro):
    return asyncio.run(coro)


# --- fence primitives (test_cross_contract_fence.py) -----------------------

def test_extract_contract_doc_ids():
    assert m.extract_contract_doc_ids(
        "Per the DD-2023-118 Infrastructure Package 1 executed contract, "
        "what is the Time for Completion for the whole of the Works?"
    ) == ["dd-2023-118"]
    assert m.extract_contract_doc_ids(DD23_NAME) == ["dd-2023-118"]
    assert m.extract_contract_doc_ids(DD22_NAME) == ["dd-2022-175"]
    assert m.extract_contract_doc_ids("What are the Delay Damages?") == []
    # Drawing codes are not PREFIX-YEAR-SEQ contract ids.
    assert m.extract_contract_doc_ids(
        "PK-INF-002-0000-FRM-DWG-LI-200-0001056-04"
    ) == []


def test_filename_match_rejects_other_year():
    # The upload filename is the authority.
    assert m.filename_matches_named_contracts(DD22_NAME, ["dd-2023-118"]) is False
    assert m.filename_matches_named_contracts(DD23_NAME, ["dd-2023-118"]) is True
    # An unresolved filename falls back to a contiguous id in chunk text...
    assert m.filename_matches_named_contracts(
        "", ["dd-2023-118"], chunk_text="see DD-2023-118 contract data",
    ) is True
    # ...but token soup ('dd' + '2023' + '118' scattered) is rejected.
    assert m.filename_matches_named_contracts(
        "", ["dd-2023-118"],
        chunk_text="the dd prefix, dated 2023, clause 118",
    ) is False
    assert m.filename_matches_named_contracts(DD22_NAME, []) is True


# --- election (test_unnamed_contract_year_lock.py) -------------------------

def test_election_picks_the_contract_owning_the_filled_row():
    """Rank 1 is another year's pointer; the row that answers is below it."""
    row = _unsplit_particulars_chunk(DD23_UNSPLIT_DELAY_LINE)
    elected = m.elect_answer_bearing_contract(
        A5, _ranked((DD22_NAME, DD22_DELAY_CLAUSE), (DD23_NAME, row)),
    )
    assert elected == "dd-2023-118"


def test_election_declines_when_no_filled_row_is_in_the_pool():
    assert m.elect_answer_bearing_contract(
        A5, _ranked((DD22_NAME, DD22_DELAY_CLAUSE)),
    ) is None


def test_election_declines_for_a_question_that_wants_no_particular():
    row = _unsplit_particulars_chunk(DD23_UNSPLIT_DELAY_LINE)
    assert m.elect_answer_bearing_contract(
        "Summarize drawing PK-INF-002-0000-FRM-DWG-LI-200-0001056-04",
        _ranked((DD23_NAME, row)),
    ) is None
    assert m.elect_answer_bearing_contract(
        "What does Accepted Contract Amount mean?", _ranked((DD23_NAME, row)),
    ) is None


def test_newer_year_owns_the_unnamed_ask_when_both_state_the_particular():
    dd23 = _unsplit_particulars_chunk(DD23_UNSPLIT_TFC_LINE)
    ranked = _ranked(
        (DD22_NAME, DD22_FILLED_TFC_548),
        (DD22_SCHED_NAME, DD22_SCHEDULE_548),
        (DD23_NAME, dd23),
    )
    assert m.elect_answer_bearing_contract(A3, ranked) == "dd-2023-118"
    assert m.elect_answer_bearing_contract(LIVE_A3, ranked) == "dd-2023-118"
    assert m.particulars_row_answers_asked_label(A3, DD22_FILLED_TFC_548)
    assert m.particulars_row_answers_asked_label(A3, dd23)
    assert not m.particulars_row_answers_asked_label(A3, DD22_SCHEDULE_548)


def test_newer_year_owns_delay_damages_when_both_years_state_a_rate():
    dd23d = _unsplit_particulars_chunk(DD23_UNSPLIT_DELAY_LINE)
    ranked = _ranked(
        (DD22_NAME, DD22_DELAY_CLAUSE),
        (DD22_NAME, DD22_FILLED_DELAY_CAP),
        (DD23_NAME, dd23d),
    )
    assert m.elect_answer_bearing_contract(A5, ranked) == "dd-2023-118"
    assert m.elect_answer_bearing_contract(LIVE_A5, ranked) == "dd-2023-118"


def test_a_delay_damages_cap_is_not_the_daily_rate():
    dd23d = _unsplit_particulars_chunk(DD23_UNSPLIT_DELAY_LINE)
    assert m.chunk_states_delay_damages_rate(dd23d)
    assert not m.chunk_states_delay_damages_rate(DD22_FILLED_DELAY_CAP)
    assert not m.chunk_states_delay_damages_rate(DD22_DELAY_CLAUSE)


# --- coverage honesty (coverage_honesty.py) --------------------------------

def test_forbidden_absence_claim_rewritten_on_partial_index():
    assert m.rewrite_forbidden_absence_claims(
        "The clause does not exist in this contract.", 2935, 6206,
    ) == "The clause not found in the 2935 indexed in this contract."


def test_absence_claim_untouched_at_full_coverage():
    assert m.rewrite_forbidden_absence_claims(
        "The clause does not exist.", 2935, 2935,
    ) == "The clause does not exist."


def test_coverage_line_stamped_once():
    out = m.apply_coverage_honesty("No such clause here.", coverage=(2935, 6206))
    assert "not found in the 2935 indexed" in out
    assert out.count("2935 of 6206 project documents indexed") == 1


def test_unknown_counts_leave_text_untouched():
    # No counts and no project -> the honesty layer does not invent numbers.
    assert m.apply_coverage_honesty("plain text") == "plain text"


# --- block envelope + refusal paths ----------------------------------------

def test_elect_block_action():
    b = ContractRetrievalBlock()
    row = _unsplit_particulars_chunk(DD23_UNSPLIT_DELAY_LINE)
    r = _run(b.process({
        "action": "elect", "query": A5,
        "ranked_docs": [(DD22_NAME, DD22_DELAY_CLAUSE), (DD23_NAME, row)],
    }))
    assert r["status"] == "ok"
    assert r["result"]["elected_contract"] == "dd-2023-118"


def test_elect_without_pool_is_refused():
    b = ContractRetrievalBlock()
    r = _run(b.process({"action": "elect", "query": A5}))
    assert r["status"] == "refused"
    assert "ranked" in r["error"]


def test_fence_without_pool_is_refused():
    b = ContractRetrievalBlock()
    r = _run(b.process({"action": "fence", "query": "DD-2023-118"}))
    assert r["status"] == "refused"


def test_fence_named_contract_fails_closed_to_empty():
    b = ContractRetrievalBlock()
    r = _run(b.process({
        "action": "fence",
        "query": "Per DD-2024-999, what are the Delay Damages?",
        "docs": [
            {"filename": DD22_NAME, "chunk_text": DD22_DELAY_CLAUSE},
            {"filename": DD23_NAME, "chunk_text": _unsplit_particulars_chunk(DD23_UNSPLIT_DELAY_LINE)},
        ],
    }))
    assert r["status"] == "refused"
    assert r["result"] is None


def test_fence_keeps_only_the_named_contract():
    b = ContractRetrievalBlock()
    r = _run(b.process({
        "action": "fence",
        "query": "Per the DD-2022-175 contract, what are the Delay Damages?",
        "docs": [
            {"filename": DD22_NAME, "chunk_text": DD22_DELAY_CLAUSE},
            {"filename": DD23_NAME, "chunk_text": _unsplit_particulars_chunk(DD23_UNSPLIT_DELAY_LINE)},
        ],
    }))
    assert r["status"] == "ok"
    assert len(r["result"]["kept"]) == 1
    assert DD22_NAME in str(r["result"]["kept"][0]["filename"])


def test_coverage_without_counts_is_refused_not_invented():
    b = ContractRetrievalBlock()
    r = _run(b.process({"action": "coverage", "text": "does not exist"}))
    assert r["status"] == "refused"
    assert "indexed" in r["error"]


def test_unknown_action_is_error():
    b = ContractRetrievalBlock()
    r = _run(b.process({"action": "nonsense"}))
    assert r["status"] == "error"
    assert r["block_id"] == "contract_retrieval"
