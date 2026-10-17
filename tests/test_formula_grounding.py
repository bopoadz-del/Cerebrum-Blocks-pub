"""Grounding: whether a generated number came from a definition or a guess.

The property under test: **an ungrounded answer must be distinguishable from
a grounded one after the fact.** Before this, both arrived as a number and
some plausible Python, and no field in the result told them apart.
"""

import json

import pytest

from app.core import formula_definitions as fd


@pytest.fixture
def product_root(tmp_path, monkeypatch):
    """A generated product with the kernel definitions vendored in."""
    kernel = tmp_path / "app" / "cerebrum_product_kernel" / "formulas"
    kernel.mkdir(parents=True)
    (kernel / "universal_definitions.json").write_text(
        json.dumps(
            {
                "set_id": "universal",
                "definitions": [
                    {
                        "id": "gross_margin_ratio",
                        "name": "Gross margin ratio",
                        "key": "universal:gross_margin_ratio_v1",
                        "tier": "base",
                        "expression": "(revenue - cogs) / revenue",
                        "inputs": ["revenue", "cogs"],
                        "guards": ["revenue != 0"],
                        "provenance": {"kind": "internal_protocol", "reference": "base tier"},
                    },
                    {
                        "id": "days_sales_outstanding",
                        "name": "Days sales outstanding",
                        "key": "universal:days_sales_outstanding_v1",
                        "tier": "base",
                        "expression": "(receivables / revenue) * days",
                        "inputs": ["receivables", "revenue", "days"],
                        "provenance": {"kind": "internal_protocol", "reference": "base tier"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CEREBRUM_PRODUCT_ROOT", str(tmp_path))
    return tmp_path


# -- the three states ------------------------------------------------------


def test_a_named_quantity_with_a_definition_is_grounded(product_root):
    report = fd.grounding_report("What is the gross margin ratio for Q3?")

    assert report["derivation"] == fd.GROUNDED
    assert report["definitions"][0]["id"] == "gross_margin_ratio"
    assert report["definitions"][0]["tier"] == "base"
    assert report["definitions"][0]["expression"] == "(revenue - cogs) / revenue"
    assert report["definitions"][0]["provenance"]["kind"] == "internal_protocol"


def test_a_named_quantity_with_no_definition_is_flagged(product_root):
    """The case the whole module exists for.

    'customer lifetime value' is a real business quantity that the base set
    does not define. The model will happily compute one. The result must say
    that the derivation is the model's.
    """
    report = fd.grounding_report("Work out the customer lifetime value")

    assert report["derivation"] == fd.MODEL_GENERATED
    assert report["definitions"] == []
    assert "not the platform" in report["note"]


def test_caller_supplied_arithmetic_is_left_alone(product_root):
    """Per the ruling: user-specified arithmetic stays free.

    Nobody is claiming a named quantity here, so there is nothing to ground
    and no flag to raise.
    """
    for task in (
        "compute length_m * width_m * thickness_m",
        "calculate 10 * 8 * 0.2",
        "evaluate (revenue - cogs) / revenue",
    ):
        assert fd.grounding_report(task)["derivation"] == fd.USER_SPECIFIED, task


# -- the failure that would make this decoration ---------------------------


def test_no_definition_set_reports_ungrounded_not_fine(monkeypatch, tmp_path):
    """With no kernel vendored, nothing is grounded -- and it must say so.

    The dangerous failure is a runtime with no definitions reporting
    'grounded' by vacuity, or reporting nothing at all so the caller assumes
    a check happened. The note has to distinguish 'we looked and found none'
    from 'there was nothing to look in'.
    """
    monkeypatch.setenv("CEREBRUM_PRODUCT_ROOT", str(tmp_path))
    report = fd.grounding_report("What is the gross margin ratio?")

    assert report["derivation"] == fd.MODEL_GENERATED
    assert report["definition_set_size"] == 0
    assert "no definition set is available" in report["note"]
    assert "not a statement that grounding was unnecessary" in report["note"]


def test_a_near_miss_does_not_ground_the_wrong_definition(product_root):
    """Matching is deliberately literal.

    'margin of error' is not 'gross margin ratio'. A fuzzy matcher that
    grounded it would attach a real provenance record to an unrelated
    number, which is worse than no grounding at all.
    """
    report = fd.grounding_report("what is the margin of error on the survey")
    assert report["derivation"] != fd.GROUNDED


# -- what reaches the model ------------------------------------------------


def test_the_definition_is_injected_into_the_prompt(product_root):
    matched = fd.match_definitions(
        "gross margin ratio please", fd.load_definitions()
    )
    block = fd.definitions_prompt_block(matched)

    assert "(revenue - cogs) / revenue" in block
    assert "revenue != 0" in block
    assert "Use them exactly" in block


def test_nothing_is_injected_when_nothing_matched(product_root):
    assert fd.definitions_prompt_block([]) == ""


def test_the_prompt_carries_definitions_before_variables(product_root):
    from app.prompts.codegen_system import build_codegen_prompt

    matched = fd.match_definitions("gross margin ratio", fd.load_definitions())
    prompt = build_codegen_prompt(
        "gross margin ratio",
        {"revenue": 100, "cogs": 60},
        definitions_block=fd.definitions_prompt_block(matched),
    )

    assert "(revenue - cogs) / revenue" in prompt
    assert prompt.index("AUTHORITATIVE DEFINITIONS") < prompt.index("INPUT VARIABLES")


def test_the_prompt_is_unchanged_when_there_is_nothing_to_ground():
    """Existing callers pass no definitions and must be unaffected."""
    from app.prompts.codegen_system import build_codegen_prompt

    prompt = build_codegen_prompt("calculate 2 + 2", {})
    assert "AUTHORITATIVE DEFINITIONS" not in prompt


# -- overlays --------------------------------------------------------------


def test_a_domain_overlay_extends_the_base_set(product_root):
    data_dir = product_root / "app" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "domain_definitions.json").write_text(
        json.dumps(
            {
                "set_id": "construction",
                "definitions": [
                    {
                        "id": "waste_factor",
                        "name": "Waste factor",
                        "expression": "ordered / installed - 1",
                        "inputs": ["ordered", "installed"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = fd.grounding_report("what is the waste factor on this package")

    assert report["derivation"] == fd.GROUNDED
    assert report["definitions"][0]["id"] == "waste_factor"
    assert report["definitions"][0]["tier"] == "domain-extension"


def test_an_overlay_replacing_a_base_id_says_what_it_replaced(product_root):
    """Even installed unresolved, the swap must not be silent.

    The kernel resolver refuses an undeclared override. If one reaches a
    product anyway, the answer still has to name the base address it
    displaced rather than quietly returning different arithmetic under the
    same name.
    """
    data_dir = product_root / "app" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "domain_definitions.json").write_text(
        json.dumps(
            {
                "set_id": "construction",
                "definitions": [
                    {
                        "id": "gross_margin_ratio",
                        "name": "Gross margin ratio",
                        "expression": "(revenue - cogs - rework) / revenue",
                        "inputs": ["revenue", "cogs", "rework"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = fd.grounding_report("gross margin ratio")
    entry = report["definitions"][0]

    assert entry["tier"] == "domain-override of base"
    assert entry["supersedes"] == "universal:gross_margin_ratio_v1"
    assert "rework" in entry["expression"]
