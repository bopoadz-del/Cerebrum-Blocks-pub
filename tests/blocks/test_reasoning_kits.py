"""Every declarative reasoning kit, driven through its own block's ``process``.

These are the tests certification bar 3 measures. Bar 3 guts a block's entry
method to a plausible success and the suite MUST go red; a suite that stays green
on a canned success proves nothing about the block's payloads. So every
assertion here reads something only a real sweep produces — the verdict, the
named reason, which hooks ran, the interview state, the unmeasured list.

The properties asserted are the ones that decide whether the layer can be
trusted at all, and they hold for every kit:

  * a scope refusal is returned BEFORE retrieval, and says retrieval was not
    permitted
  * an undeclared qualifier is refused rather than quietly ignored
  * every hook in the routing map actually runs — a host that reaches only
    answer-time silently gets no authority or band coverage
  * no value has been filled, and the block says so with every answer
  * an unloadable kit REFUSES; it never passes statements through
"""
from __future__ import annotations

import asyncio
import importlib
import pathlib
import re

import pytest
import yaml

from app.blocks.kit_engine import load_kit
from app.blocks.kit_engine.engine import DisabledKit

BLOCKS = pathlib.Path("app/blocks")

#: Every kit that ships a declared half. Discovered, not listed: a kit added
#: without a test is the gap this file exists to close.
KIT_NAMES = sorted(
    p.parent.name for p in BLOCKS.glob("*/manifest.yaml")
    if (p.parent / "invariants.yaml").is_file()
)


def _block(kit: str):
    module = importlib.import_module(f"app.blocks.{kit}_kit")
    for attr in dir(module):
        value = getattr(module, attr)
        if isinstance(value, type) and getattr(value, "kit_name", None) == kit:
            return value()
    raise AssertionError(f"no block class for kit {kit}")


def _run(block, payload: dict) -> dict:
    return asyncio.run(block.process(payload, {}))


def test_every_kit_declares_both_halves():
    assert KIT_NAMES, "no declared kits found"
    for kit in KIT_NAMES:
        assert (BLOCKS / kit / "manifest.yaml").is_file()
        assert (BLOCKS / kit / "invariants.yaml").is_file()
        assert (BLOCKS / f"{kit}_kit.py").is_file(), f"{kit} has no store-facing block"


@pytest.mark.parametrize("kit", KIT_NAMES)
def test_the_kit_loads_and_gates(kit):
    """Fail closed: a kit that does not parse is disabled and refuses. None of
    these may be disabled, and none may load with zero invariants."""
    loaded = load_kit(BLOCKS / kit)
    assert loaded.invariants, f"{kit} loaded with no invariants"
    assert loaded.manifest.quantities, f"{kit} declares no quantities"


@pytest.mark.parametrize("kit", KIT_NAMES)
def test_every_kit_refuses_its_scope_questions_before_retrieval(kit):
    """H0. No document makes an operational-authority question answerable, so
    retrieving at all is wrong — it produces citations that read as though they
    authorised the decision."""
    manifest = yaml.safe_load((BLOCKS / kit / "manifest.yaml").read_text(encoding="utf-8"))
    refusals = manifest.get("scope_refusals") or []
    assert refusals, f"{kit} declares no scope refusals"

    # Every declared pattern must actually refuse. The probe is generated from
    # the pattern and then CHECKED against it, so a probe that fails to match
    # fails the test rather than passing it quietly.
    for refusal in refusals:
        pattern = str(refusal["pattern"])
        probe = _probe_for(pattern)
        assert re.search(pattern, probe, re.IGNORECASE), (
            f"{kit}: could not build a probe for {pattern!r} (got {probe!r})"
        )

        envelope = _run(_block(kit), {"question": probe})

        assert envelope["status"] == "success", envelope
        result = envelope["result"]
        assert result["verdict"] == "refused", (kit, probe, result)
        assert result["retrieval_permitted"] is False
        assert "before retrieval" in result["blocked_reason"]
        assert result["hooks_run"] == ["H0"], "H0 must return alone when it refuses"


def test_the_scope_probe_generator_is_honest():
    """The generator above is test machinery. If it silently produced strings the
    patterns do not match, every scope test would pass on nothing."""
    assert re.search(r"can we (start|begin) (the )?(lift|lay)",
                     _probe_for(r"can we (start|begin) (the )?(lift|lay)"), re.IGNORECASE)
    assert re.search(r"can we hand (this\s+|it\s+)?back(\s+tonight)?",
                     _probe_for(r"can we hand (this\s+|it\s+)?back(\s+tonight)?"), re.IGNORECASE)


def _first_in_class(members: str) -> str:
    """One character a `[...]` class accepts. `\s` becomes a space."""
    if members.startswith("^"):
        return "x"
    if members[0] == "\\" and len(members) > 1:
        return " " if members[1] == "s" else members[1]
    return members[0]


def _probe_for(pattern: str) -> str:
    """Build a question the pattern matches: take the first alternative of every
    group, expand the whitespace classes, and drop the regex punctuation."""
    text = pattern
    # Innermost groups first, repeatedly, so nesting resolves. Both capturing
    # `(a|b)` and non-capturing `(?:a|b)` -- missing the second left a literal
    # "(:the )" in the probe and the assertion caught it.
    for _ in range(8):
        collapsed = re.sub(
            r"\((?:\?:)?([^()]*)\)",
            lambda m: m.group(1).split("|")[0],
            text,
        )
        if collapsed == text:
            break
        text = collapsed
    text = text.split("|")[0]
    # Character classes: take the first member. `four[-\s]?foot` becomes
    # `four-foot`, which the pattern matches; leaving the brackets in did not.
    text = re.sub(r"\[([^\]]+)\]", lambda m: _first_in_class(m.group(1)), text)
    text = text.replace(r"\s+", " ").replace(r"\s*", " ")
    text = text.replace(".?", " ").replace(r"\.", ".")
    text = re.sub(r"\\b", "", text)
    text = text.replace("?", "").replace("^", "").replace("$", "")
    text = text.replace("\\", "")
    return re.sub(r"\s{2,}", " ", text).strip()




@pytest.mark.parametrize("kit", KIT_NAMES)
def test_every_kit_runs_the_whole_routing_map(kit):
    """A host that calls answer-time alone silently gets no authority (H1) or
    band (H2) coverage. The block runs all five by default and says which."""
    quantity = sorted(load_kit(BLOCKS / kit).manifest.quantities)[0]

    envelope = _run(_block(kit), {
        "question": "what figure applies here?",
        "figures": [{"quantity": quantity, "origin": "model", "text": "a bare claim"}],
    })

    result = envelope["result"]
    assert result["hooks_run"] == ["H0", "H1", "H2", "H3", "H4"], result["hooks_run"]
    assert result["retrieval_permitted"] is True


@pytest.mark.parametrize("kit", KIT_NAMES)
def test_an_ungrounded_or_unqualified_figure_is_never_waved_through(kit):
    """A bare model-origin figure with no qualifiers must not pass. Whether it
    is grounding, a qualifier or authority that catches it is the kit's business;
    that SOMETHING catches it is the layer's."""
    quantity = sorted(load_kit(BLOCKS / kit).manifest.quantities)[0]

    result = _run(_block(kit), {
        "figures": [{"quantity": quantity, "value": 1, "origin": "model",
                     "text": "a figure from nowhere"}],
    })["result"]

    assert result["verdict"] in ("refused", "flagged"), (kit, result)
    assert result["findings"], f"{kit} produced no finding for an ungrounded figure"


@pytest.mark.parametrize("kit", KIT_NAMES)
def test_an_undeclared_qualifier_is_refused_not_ignored(kit):
    """An invariant reading a field it cannot trust is worse than no invariant."""
    quantity = sorted(load_kit(BLOCKS / kit).manifest.quantities)[0]

    result = _run(_block(kit), {
        "figures": [{"quantity": quantity, "origin": "document", "source_id": "d1",
                     "qualifiers": {"not_a_declared_field": "x"}, "text": "a claim"}],
    })["result"]

    assert result["verdict"] == "refused"
    assert any("not a declared qualifier field" in f["message"] for f in result["findings"])


@pytest.mark.parametrize("kit", KIT_NAMES)
def test_the_interview_state_travels_with_every_answer(kit):
    """No interview has run for any of these domains. A caller must be able to
    see that no value is filled, and which records are unmeasured, without
    asking."""
    result = _run(_block(kit), {"question": "what figure applies here?"})["result"]

    assert "interview_status" in result
    assert isinstance(result["unfilled_figures"], list)
    assert isinstance(result["unmeasured_invariants"], list)
    assert result["kit_disabled"] is False
    # ships is False while any record lacks a measurement case -- spec §4, at the
    # ship gate rather than the load gate.
    assert result["ships"] is (result["unmeasured_invariants"] == [])


@pytest.mark.parametrize("kit", KIT_NAMES)
def test_a_request_with_neither_question_nor_figure_is_refused(kit):
    envelope = _run(_block(kit), {})
    assert envelope["status"] == "refused"
    assert "question" in envelope["error"] and "figure" in envelope["error"]


@pytest.mark.parametrize("kit", KIT_NAMES)
def test_a_malformed_figure_is_refused_rather_than_coerced(kit):
    envelope = _run(_block(kit), {"figures": ["not a mapping"]})
    assert envelope["status"] == "refused"
    assert "mapping" in envelope["error"]


def test_a_disabled_kit_refuses_every_statement():
    """The whole safety property, through the block: a typo must not become
    "no invariants"."""
    from app.blocks.kit_block import ReasoningKitBlock

    class Broken(ReasoningKitBlock):
        name = "broken_reasoning"
        kit_name = "no_such_kit_on_disk"
        description = "probe"
        tags: list = []

        async def process(self, input_data, params):
            return await self.run_kit(input_data, params)

    envelope = asyncio.run(Broken().process({"question": "anything at all?"}, {}))
    result = envelope["result"]

    assert result["kit_disabled"] is True
    assert result["verdict"] == "refused"
    assert "DISABLED" in result["blocked_reason"]
    assert "does not pass statements through" in result["blocked_reason"]


def test_the_block_never_infers_a_qualifier_from_prose():
    """Inferring a qualifier from the words around a figure IS the defect. A
    figure whose prose mentions a datum but whose qualifiers do not carry it must
    still be treated as missing it."""
    from app.blocks.kit_block import figures_from

    figure = figures_from([{
        "quantity": "declared_distance",
        "text": "TORA 3200 m on runway 13L, permanent, effective 2026-01-01",
    }])[0]

    assert figure.qualifiers == {}, "prose leaked into the qualifiers"
    assert figure.claim_class is None
    assert figure.source_class is None
