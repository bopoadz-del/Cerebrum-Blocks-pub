"""The block result contract, and the guarantee that adopting it costs no
existing block anything.

Two properties are under test here.

**A result can only say something it can back up.** Every status that is not
``ok`` carries a reason, coverage is a fraction or an honest ``None``, and an
ungrounded number is distinguishable from a sourced one.

**Nothing had to be edited to get this.** The adapter takes what the 129
blocks in this store return today -- bare dicts, strings, ``success``/
``error`` -- and produces a result without any of them knowing this module
exists.
"""

import pytest

from app.core.block_result import (
    FAILED,
    OK,
    PARTIAL,
    REFUSED,
    SCORED_AS_PASS,
    STATUSES,
    BlockResult,
    ContractViolation,
    provenance_from_grounding,
    to_block_result,
)
from app.core.contract_block import ContractBlock, safe_call
from app.core.universal_base import UniversalBlock


# -- the four statuses -----------------------------------------------------


def test_the_four_statuses_are_the_whole_set():
    assert STATUSES == {"ok", "partial", "failed", "refused"}


def test_ok_needs_no_reason_and_carries_its_data():
    result = BlockResult.ok({"volume_m3": 16.0})
    assert result.status == OK
    assert result.is_ok
    assert result.reason is None
    assert result.data == {"volume_m3": 16.0}


def test_partial_says_how_much_and_what_is_missing():
    result = BlockResult.partial(
        "3 of 11 invoices had no line items", data={"priced": 8}, coverage=8 / 11
    )
    assert result.status == PARTIAL
    assert "3 of 11" in result.reason
    assert result.coverage == pytest.approx(0.727, abs=0.001)


def test_failed_says_why_in_words_not_a_traceback():
    result = BlockResult.failed("the rate table for 2026 has not been published")
    assert result.status == FAILED
    assert not result.is_ok
    assert "rate table" in result.reason


def test_refused_is_a_pass_and_failed_is_not():
    """The reason refusal is a status of its own.

    Folding it into ``failed`` teaches the scoreboard that declining to invent
    an answer is a defect, and the cheapest way to score better under that
    rule is to answer anyway.
    """
    refusal = BlockResult.refused("no source in the kit covers 2026 rates")
    failure = BlockResult.failed("the rate table could not be read")

    assert refusal.status == REFUSED
    assert refusal.scored_as_pass is True
    assert failure.scored_as_pass is False


def test_partial_is_deliberately_not_scored_as_a_pass():
    """Only ``refused`` was specified as a pass. Whether a partial answer
    counts depends on a coverage floor this module does not get to set."""
    assert SCORED_AS_PASS == {OK, REFUSED}
    assert BlockResult.partial("half the rows", coverage=0.5).scored_as_pass is False


# -- what a result may not claim -------------------------------------------


@pytest.mark.parametrize("status", ["partial", "failed", "refused"])
def test_a_status_that_is_not_ok_must_carry_a_reason(status):
    with pytest.raises(ContractViolation) as excinfo:
        BlockResult(status=status)
    assert "requires a reason" in str(excinfo.value)


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_a_blank_reason_is_not_a_reason(blank):
    with pytest.raises(ContractViolation):
        BlockResult(status=FAILED, reason=blank)


def test_an_unknown_status_is_a_defect_not_a_new_state():
    with pytest.raises(ContractViolation) as excinfo:
        BlockResult(status="mostly_fine", reason="hmm")
    assert "unknown status" in str(excinfo.value)


@pytest.mark.parametrize("bad", [-0.1, 1.1, "0.5", True])
def test_coverage_is_a_fraction_or_nothing(bad):
    with pytest.raises(ContractViolation):
        BlockResult.ok({}, coverage=bad)


def test_coverage_none_is_legitimate_and_is_not_zero():
    """"I cannot measure how much of this I answered" is an honest answer and
    must not be recorded as "I answered none of it"."""
    unmeasured = BlockResult.ok({})
    measured_zero = BlockResult.partial("nothing matched", coverage=0.0)

    assert unmeasured.coverage is None
    assert measured_zero.coverage == 0.0
    assert unmeasured.coverage is not measured_zero.coverage


def test_every_key_is_present_on_every_result():
    """#82's lesson: a consumer must not need to know which code path ran in
    order to avoid a KeyError."""
    for result in (
        BlockResult.ok(1),
        BlockResult.partial("p", coverage=0.5),
        BlockResult.failed("f"),
        BlockResult.refused("r"),
    ):
        payload = result.to_dict()
        assert set(payload) == {
            "status",
            "reason",
            "coverage",
            "provenance",
            "evidence",
            "data",
        }


def test_a_single_provenance_record_is_taken_as_one_entry():
    result = BlockResult.ok({}, provenance={"derivation": "grounded"})
    assert result.provenance == [{"derivation": "grounded"}]


# -- provenance, extending #82's grounding field ---------------------------


def test_a_grounded_report_yields_one_entry_per_definition():
    grounding = {
        "derivation": "grounded",
        "definitions": [
            {
                "id": "gross_profit",
                "tier": "base",
                "expression": "revenue - cogs",
                "key": "universal:gross_profit_v1",
                "provenance": {"kind": "internal_protocol", "reference": "base"},
            }
        ],
        "definition_set_size": 29,
    }
    entries = provenance_from_grounding(grounding)

    assert len(entries) == 1
    assert entries[0]["id"] == "gross_profit"
    assert entries[0]["tier"] == "base"
    assert entries[0]["source"]["kind"] == "internal_protocol"


def test_an_ungrounded_answer_still_records_that_it_was_ungrounded():
    """Dropping the record would leave a model-generated number looking
    identical to a sourced one -- the defect #82 exists to prevent."""
    entries = provenance_from_grounding(
        {
            "derivation": "model_generated",
            "definitions": [],
            "note": "no platform definition matched this task",
        }
    )
    assert len(entries) == 1
    assert entries[0]["derivation"] == "model_generated"
    assert entries[0]["id"] is None
    assert "no platform definition" in entries[0]["note"]


@pytest.mark.parametrize("junk", [None, "grounded", 42, []])
def test_a_missing_grounding_field_yields_no_provenance_rather_than_a_crash(junk):
    assert provenance_from_grounding(junk) == []


# -- the adapter -----------------------------------------------------------


def test_a_legacy_raw_dict_becomes_ok_with_its_payload_intact():
    """The reason no existing block had to be edited."""
    raw = {"value": "hello", "hit": True}
    result = to_block_result(raw)

    assert result.status == OK
    assert result.data == raw


@pytest.mark.parametrize("legacy", ["success", "ok", "completed", "SUCCESS", " ok "])
def test_the_success_vocabulary_maps_onto_ok(legacy):
    assert to_block_result({"status": legacy}).status == OK


def test_a_legacy_error_becomes_failed_and_keeps_its_message():
    result = to_block_result({"status": "error", "error": "Redis unreachable"})
    assert result.status == FAILED
    assert result.reason == "Redis unreachable"


def test_a_legacy_error_with_no_message_still_gets_a_reason():
    result = to_block_result({"status": "error"})
    assert result.status == FAILED
    assert result.reason.strip()


def test_a_grounding_field_on_a_legacy_result_is_lifted_into_provenance():
    result = to_block_result(
        {
            "status": "success",
            "result": 40,
            "grounding": {
                "derivation": "grounded",
                "definitions": [{"id": "gross_profit", "tier": "base"}],
            },
        }
    )
    assert result.status == OK
    assert result.provenance[0]["id"] == "gross_profit"


def test_none_is_the_one_raw_return_that_is_not_ok():
    """A block that returned nothing did not succeed quietly."""
    result = to_block_result(None)
    assert result.status == FAILED
    assert "None" in result.reason


@pytest.mark.parametrize("scalar", ["some text", 42, 0, ["a", "b"], False])
def test_a_non_dict_return_becomes_ok_carrying_the_value(scalar):
    result = to_block_result(scalar)
    assert result.status == OK
    assert result.data == scalar


def test_an_unrecognised_status_is_not_assumed_to_be_fine():
    result = to_block_result({"status": "probably_ok"})
    assert result.status == FAILED
    assert "unrecognised" in result.reason


def test_a_result_that_is_already_a_result_passes_straight_through():
    original = BlockResult.refused("no source")
    assert to_block_result(original) is original


def test_confidence_is_not_silently_read_as_coverage():
    """Confidence is how sure the block is; coverage is how much of the
    question it answered. A very sure answer to a tenth of the question must
    not read as nine-tenths done."""
    result = to_block_result({"status": "success", "confidence": 0.95})
    assert result.coverage is None


# -- the guard -------------------------------------------------------------


class _Exploding(ContractBlock):
    name = "exploding"

    async def process(self, input_data, params=None):
        raise ZeroDivisionError("division by zero")


class _ReturnsNothing(ContractBlock):
    name = "returns_nothing"

    async def process(self, input_data, params=None):
        return None


class _Synchronous(UniversalBlock):
    """Not every block in this store defines ``process`` as ``async def``."""

    name = "synchronous"

    def process(self, input_data, params=None):
        return {"status": "success", "echo": input_data}


class _LegacyBlock(UniversalBlock):
    """A block written before any of this existed. Untouched."""

    name = "legacy"

    async def process(self, input_data, params=None):
        return {"rows": 3}


async def test_a_planted_exception_becomes_failed_with_a_reason_not_a_crash():
    result = await _Exploding().run({})

    assert result.status == FAILED
    assert "ZeroDivisionError" in result.reason
    assert "division by zero" in result.reason


async def test_the_traceback_is_kept_as_evidence():
    result = await _Exploding().run({})

    assert result.evidence, "the traceback was dropped"
    assert result.evidence[0]["error_type"] == "ZeroDivisionError"
    assert "ZeroDivisionError" in result.evidence[0]["traceback"]


async def test_the_reason_names_the_block_that_failed():
    """A pipeline of thirty blocks reporting 'failed' names nothing."""
    result = await _Exploding().run({})
    assert "exploding" in result.reason


async def test_the_flag_lets_the_exception_through_for_a_debugger():
    block = _Exploding()
    block.config["reraise_exceptions"] = True

    with pytest.raises(ZeroDivisionError):
        await block.run({})


async def test_a_block_returning_none_is_reported_not_swallowed():
    result = await _ReturnsNothing().run({})
    assert result.status == FAILED


async def test_a_synchronous_process_is_accepted():
    result = await safe_call(_Synchronous(), "hi")
    assert result.status == OK
    assert result.data["echo"] == "hi"


async def test_an_untouched_legacy_block_yields_a_result_through_safe_call():
    """``safe_call`` is what lets the store-wide harness get a status out of
    blocks that have never heard of this module."""
    block = _LegacyBlock()
    result = await safe_call(block, {})

    assert result.status == OK
    assert result.data == {"rows": 3}


async def test_safe_call_does_not_change_what_the_legacy_block_returns():
    """The non-breaking guarantee, stated as a test: the block's own return
    value is byte-for-byte what it always was."""
    block = _LegacyBlock()
    direct = await block.process({}, {})
    wrapped = await safe_call(block, {})

    assert wrapped.data == direct


async def test_execute_is_untouched_by_adoption():
    """A ContractBlock dropped into an existing pipeline behaves like any
    other block: same envelope, same vocabulary."""
    envelope = await _ReturnsNothing().execute({})

    assert set(envelope) >= {"block", "request_id", "status", "result", "confidence"}
    assert envelope["status"] in ("success", "error")
