"""Grounding, exercised the way a generated product actually runs it.

`test_formula_grounding.py` proves the resolver's logic against fixtures.
This file closes the two gaps that leaves:

1. **Nobody had ever run the resolver against the real kernel set.** The
   definitions live in the other repository and reach a product through
   ``generator._write_app``'s copytree. The two halves had only ever met
   through a fixture I wrote, which means a schema change on either side
   would have gone unnoticed until a client saw it.

2. **Nobody had run the block.** The resolver returning the right answer and
   the executor putting that answer in its output are different claims.

The cross-repo test skips, loudly, when the kernel is not checked out beside
this repo -- CI does not have it. The block tests build their own product
tree and always run.
"""

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: Where the kernel lives when both repos are checked out side by side.
#: Overridable so a CI job that does check both out can point at either.
_KERNEL_CANDIDATES = [
    Path(os.environ["CEREBRUM_KERNEL_SRC"]) if os.environ.get("CEREBRUM_KERNEL_SRC") else None,
    REPO.parent / "<private-repo>" / "backend" / "app" / "cerebrum_product_kernel",
]


def _kernel_source():
    for candidate in _KERNEL_CANDIDATES:
        if candidate and (candidate / "formulas" / "universal_definitions.json").is_file():
            return candidate
    return None


def _product_with_kernel(tmp_path, overlay=None):
    """Replay generator._write_app's copytree into a product tree."""
    source = _kernel_source()
    if source is None:
        pytest.skip(
            "the product kernel is not checked out beside this repo; set "
            "CEREBRUM_KERNEL_SRC to run the cross-repo grounding proof"
        )
    dest = tmp_path / "app" / "cerebrum_product_kernel"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    if overlay is not None:
        path = tmp_path / "app" / "data" / "domain_definitions.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(overlay), encoding="utf-8")
    return tmp_path


_DENTAL_OVERLAY = {
    "set_id": "dental",
    "definitions": [
        {
            "id": "chair_utilisation",
            "expression": "booked_hours / available_hours",
            "inputs": ["booked_hours", "available_hours"],
            "provenance": {"kind": "company_policy", "reference": "Ops manual s4.2"},
        }
    ],
}


# -- the cross-repo proof --------------------------------------------------


def test_the_real_kernel_set_loads_in_a_generated_product(tmp_path, monkeypatch):
    product = _product_with_kernel(tmp_path, _DENTAL_OVERLAY)
    monkeypatch.setenv("CEREBRUM_PRODUCT_ROOT", str(product))
    from app.core import formula_definitions as fd

    definitions = fd.load_definitions()
    tiers = {}
    for entry in definitions:
        tiers[entry.get("tier")] = tiers.get(entry.get("tier"), 0) + 1

    assert tiers.get("base", 0) >= 25, f"the base tier did not arrive: {tiers}"
    assert tiers.get("domain-extension") == 1, "the kit overlay did not arrive"


def test_a_real_base_definition_grounds_with_its_real_provenance(tmp_path, monkeypatch):
    """Not a fixture: this is the definition the other repo actually ships."""
    product = _product_with_kernel(tmp_path)
    monkeypatch.setenv("CEREBRUM_PRODUCT_ROOT", str(product))
    from app.core import formula_definitions as fd

    report = fd.grounding_report("what is the gross profit for Q3?")

    assert report["derivation"] == fd.GROUNDED
    entry = report["definitions"][0]
    assert entry["id"] == "gross_profit"
    assert entry["tier"] == "base"
    assert entry["expression"], "the real set shipped an empty expression"
    assert entry["provenance"].get("kind"), "the real set shipped no provenance kind"


def test_an_overlay_definition_outranks_nothing_and_reports_its_own_tier(
    tmp_path, monkeypatch
):
    product = _product_with_kernel(tmp_path, _DENTAL_OVERLAY)
    monkeypatch.setenv("CEREBRUM_PRODUCT_ROOT", str(product))
    from app.core import formula_definitions as fd

    report = fd.grounding_report("compute chair utilisation for the clinic")
    entry = report["definitions"][0]

    assert report["derivation"] == fd.GROUNDED
    assert entry["id"] == "chair_utilisation"
    assert entry["tier"] == "domain-extension"
    # and the base set is still intact alongside it
    assert fd.grounding_report("gross profit")["definitions"][0]["tier"] == "base"


@pytest.mark.parametrize(
    "task,expected",
    [
        ("work out the customer lifetime value", "model_generated"),
        ("calculate 10 * 8 * 0.2", "user_specified"),
    ],
)
def test_the_other_two_states_hold_against_the_real_set(
    tmp_path, monkeypatch, task, expected
):
    """A 29-definition set is a much wider net than a 2-entry fixture. If
    matching were loose, this is where it would show."""
    product = _product_with_kernel(tmp_path, _DENTAL_OVERLAY)
    monkeypatch.setenv("CEREBRUM_PRODUCT_ROOT", str(product))
    from app.core import formula_definitions as fd

    assert fd.grounding_report(task)["derivation"] == expected


# -- the block ------------------------------------------------------------


def _fixture_product(tmp_path):
    """A product tree that does not need the sibling repo."""
    formulas = tmp_path / "app" / "cerebrum_product_kernel" / "formulas"
    formulas.mkdir(parents=True)
    (formulas / "universal_definitions.json").write_text(
        json.dumps(
            {
                "set_id": "universal",
                "definitions": [
                    {
                        "id": "gross_profit",
                        "name": "Gross profit",
                        "key": "universal:gross_profit_v1",
                        "tier": "base",
                        "expression": "revenue - cogs",
                        "inputs": ["revenue", "cogs"],
                        "provenance": {"kind": "internal_protocol", "reference": "base"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def _run(block, payload):
    return asyncio.run(block.process(payload))


def _stub_block(reply):
    from app.blocks.formula_executor_v2 import FormulaExecutorV2Block

    class Stub(FormulaExecutorV2Block):
        captured = None

        async def _call_llm(self, prompt):
            Stub.captured = prompt
            return reply

    return Stub()


def test_the_block_attaches_grounding_to_a_successful_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("CEREBRUM_PRODUCT_ROOT", str(_fixture_product(tmp_path)))
    block = _stub_block("```python\nresult = revenue - cogs\n```")

    out = _run(block, {"task": "what is the gross profit?",
                       "variables": {"revenue": 100, "cogs": 60}})

    assert out["status"] == "success"
    assert out["result"] == 40
    assert out["grounding"]["derivation"] == "grounded"
    assert out["grounding"]["definitions"][0]["tier"] == "base"


def test_the_definition_reaches_the_model(tmp_path, monkeypatch):
    """Reporting the tier is half of it; the model must also be told."""
    monkeypatch.setenv("CEREBRUM_PRODUCT_ROOT", str(_fixture_product(tmp_path)))
    block = _stub_block("```python\nresult = revenue - cogs\n```")
    _run(block, {"task": "what is the gross profit?",
                 "variables": {"revenue": 100, "cogs": 60}})

    assert "AUTHORITATIVE DEFINITIONS" in type(block).captured
    assert "revenue - cogs" in type(block).captured


@pytest.mark.parametrize(
    "payload,reply",
    [
        ({"task": "", "variables": {}}, "```python\nresult = 1\n```"),
        ({"task": "customer lifetime value", "variables": {"a": 1}},
         "```python\nresult = undefined_name\n```"),
    ],
)
def test_every_exit_carries_a_grounding_record(tmp_path, monkeypatch, payload, reply):
    """The regression this file caught.

    Adding grounding to the success paths alone reintroduced exactly the
    defect ``_error``'s docstring says it exists to prevent: a caller reading
    ``result["grounding"]`` got a KeyError on some paths and not others.
    """
    monkeypatch.setenv("CEREBRUM_PRODUCT_ROOT", str(_fixture_product(tmp_path)))
    block = _stub_block(reply)
    block.config["max_retries"] = 0

    out = _run(block, payload)

    assert out["status"] == "error"
    assert "grounding" in out, "an error exit dropped the grounding key"
    assert out["grounding"]["derivation"] in (
        "not_assessed", "model_generated", "user_specified", "grounded",
    )


def test_a_task_rejected_before_assessment_says_not_assessed(tmp_path, monkeypatch):
    """Distinct from model_generated: nothing was generated to assess."""
    monkeypatch.setenv("CEREBRUM_PRODUCT_ROOT", str(_fixture_product(tmp_path)))
    from app.core import formula_definitions as fd

    out = _run(_stub_block("```python\nresult = 1\n```"), {"task": "", "variables": {}})
    assert out["grounding"]["derivation"] == fd.NOT_ASSESSED
    assert "did not complete" in out["grounding"]["note"]
