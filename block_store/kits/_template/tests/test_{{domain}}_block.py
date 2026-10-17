"""The three tests every block in this store must have.

Generated with the block. They pass as-is; keep all three as you replace the
block's body, because each one catches a different way a block lies.

1. HAPPY PATH -- it does the thing.

2. PLANTED FAILURE -- when a dependency breaks, the failure is VISIBLE.
   The assertion is on ``status`` and ``reason``, not on "no exception was
   raised". A block that swallows an error and returns an empty-but-cheerful
   result passes a no-exception test and fails this one, which is the whole
   reason this test exists.

3. MUTATION PROBE -- take away something the block needs (an input, a
   definition) and it must degrade visibly. Never a confident answer built
   on what is no longer there. Of The Fork's last 100 merges, ~24 were
   failures that still looked like answers; this is the test that catches
   that class before a kit ships.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

_BLOCK_PATH = (
    Path(__file__).resolve().parents[1] / "blocks" / "{{domain}}_block.py"
)
_spec = importlib.util.spec_from_file_location("{{domain}}_block", _BLOCK_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules["{{domain}}_block"] = _module
_spec.loader.exec_module(_module)

{{Domain}}Block = _module.{{Domain}}Block


def run(block, payload, params=None):
    """Invoke the block under the base-class guard."""
    return asyncio.run(block.run(payload, params))


RECORDS = [{"amount": 10}, {"amount": 32.5}, {"amount": 7.5}]


# -- 1. happy path ---------------------------------------------------------


def test_it_summarises_the_records_it_was_given():
    result = run({{Domain}}Block(), {"records": RECORDS})

    assert result.status == "ok", result.reason
    assert result.data["total"] == pytest.approx(50.0)
    assert result.data["records"] == 3
    assert result.coverage == 1.0


def test_a_successful_answer_says_where_its_number_came_from():
    """An unsourced number and a sourced one must not look identical."""
    result = run({{Domain}}Block(), {"records": RECORDS})

    assert result.provenance, "the answer carries no provenance"
    assert result.provenance[0]["derivation"] == "grounded"


# -- 2. planted failure ----------------------------------------------------


class _BrokenDefinitions({{Domain}}Block):
    """The kit's definition source is unreadable."""

    def known_fields(self):
        raise RuntimeError("definition set could not be read")


def test_a_broken_dependency_is_reported_not_swallowed():
    result = run(_BrokenDefinitions(), {"records": RECORDS})

    # The assertion is on the STATUS and the REASON. "It did not raise" is
    # not evidence of anything: a block that catches an error and returns an
    # empty success would pass that, and this is what it must not do.
    assert result.status == "failed"
    assert "definition set could not be read" in result.reason
    assert "RuntimeError" in result.reason


def test_the_planted_failure_carries_evidence_a_reader_can_follow():
    result = run(_BrokenDefinitions(), {"records": RECORDS})

    assert result.evidence, "the failure named no evidence"
    assert result.evidence[0]["error_type"] == "RuntimeError"


def test_the_planted_failure_does_not_return_a_number():
    """The failure that matters is not the crash -- it is the total that
    appears anyway."""
    result = run(_BrokenDefinitions(), {"records": RECORDS})

    assert not (result.data or {}).get("total") if isinstance(result.data, dict) else True
    assert result.status != "ok"


# -- 3. mutation probe -----------------------------------------------------


class _DefinitionRemoved({{Domain}}Block):
    """The kit no longer declares the definition the answer needed."""

    def known_fields(self):
        return set()


def test_removing_the_definition_degrades_visibly():
    result = run(_DefinitionRemoved(), {"records": RECORDS})

    assert result.status == "refused", (
        "with its definition removed the block still answered with %r"
        % (result.status,)
    )
    assert "declares no definition" in result.reason


def test_removing_the_definition_never_produces_a_confident_total():
    """The exact shape of the ~24-in-100 failure: the arithmetic still works
    with the definition gone, so a careless block returns 50.0 and sounds
    certain. It must not."""
    result = run(_DefinitionRemoved(), {"records": RECORDS})

    assert result.status not in ("ok", "partial")
    assert "total" not in (result.data or {})


def test_removing_the_input_is_refused_rather_than_answered():
    result = run({{Domain}}Block(), {"records": []})

    assert result.status == "refused"
    assert "nothing to summarise" in result.reason


def test_a_partial_answer_names_what_it_left_out():
    """Degradation must be legible, not just non-zero."""
    result = run(
        {{Domain}}Block(),
        {"records": [{"amount": 10}, {"amount": None}, {"note": "no amount"}]},
    )

    assert result.status == "partial"
    assert "2 of 3" in result.reason
    assert result.coverage == pytest.approx(1 / 3)


# -- the contract itself ---------------------------------------------------


def test_every_exit_returns_a_block_result_with_a_reason_when_not_ok():
    cases = [
        ({{Domain}}Block(), {"records": RECORDS}),
        ({{Domain}}Block(), {"records": []}),
        (_DefinitionRemoved(), {"records": RECORDS}),
        (_BrokenDefinitions(), {"records": RECORDS}),
    ]
    for block, payload in cases:
        result = run(block, payload)
        assert result.status in ("ok", "partial", "failed", "refused")
        if result.status != "ok":
            assert (result.reason or "").strip(), "a non-ok exit gave no reason"


def test_an_honest_refusal_is_scored_as_a_pass():
    """Refusing to invent an answer is doctrine working, not a defect."""
    assert run(_DefinitionRemoved(), {"records": RECORDS}).scored_as_pass
