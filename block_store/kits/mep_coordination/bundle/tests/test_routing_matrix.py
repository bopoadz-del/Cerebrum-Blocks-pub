"""test_routing_matrix -- the golden matrix is a contract, not a fixture.

routing/golden_matrix.json is the record of what this kit promises to route
correctly, and what it promises NOT to swallow. These tests do not call a
live router (this kit has none of its own -- routing happens upstream, in
the host that dispatches to installed kits); they hold the matrix itself to
the shape a router-level test elsewhere is entitled to assume:

  a) every row has all four required fields, and a real utterance
  b) every expect_tool is either one of THIS kit's declared tools, or
     explicitly null (a negative row -- must NOT route here)
  c) no utterance appears twice, so the matrix cannot silently disagree
     with itself about the same input
  d) at least five negative rows exist, so the matrix cannot be trivially
     satisfied by only ever asserting success

A matrix with a real confusion (bim_extractor vs. this kit, both take an
IFC) that only ever tests the happy path would pass every one of THIS kit's
own tests while still routing quantity-takeoff prompts here. That is what
the negative-row floor in (d) exists to catch.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

MATRIX_PATH = (
    Path(__file__).resolve().parents[2] / "routing" / "golden_matrix.json"
)

REQUIRED_FIELDS = ("utterance", "expect_tool", "expect_action", "note")

MIN_ROWS = 20
MIN_NEGATIVE_ROWS = 5


def _load_matrix() -> dict:
    text = MATRIX_PATH.read_text(encoding="utf-8")
    return json.loads(text)


@pytest.fixture(scope="module")
def matrix() -> dict:
    return _load_matrix()


@pytest.fixture(scope="module")
def rows(matrix: dict) -> list[dict]:
    return matrix["rows"]


@pytest.fixture(scope="module")
def declared_tools(matrix: dict) -> set[str]:
    tools = matrix["tools"]
    assert tools, "golden_matrix.json declares no tools -- nothing to route to"
    return set(tools)


def test_the_matrix_file_exists_and_parses():
    assert MATRIX_PATH.exists(), f"golden matrix missing at {MATRIX_PATH}"
    data = _load_matrix()
    assert isinstance(data, dict)
    assert isinstance(data.get("rows"), list)


def test_the_matrix_has_at_least_twenty_rows(rows: list[dict]):
    assert len(rows) >= MIN_ROWS, (
        f"golden_matrix.json has {len(rows)} rows; the order requires at "
        f"least {MIN_ROWS}"
    )


def test_every_row_has_all_four_fields_and_a_non_empty_utterance(rows: list[dict]):
    for i, row in enumerate(rows):
        missing = [f for f in REQUIRED_FIELDS if f not in row]
        assert not missing, f"row {i} ({row!r}) is missing field(s): {missing}"
        utterance = row["utterance"]
        assert isinstance(utterance, str) and utterance.strip(), (
            f"row {i} has an empty or non-string utterance: {utterance!r}"
        )
        note = row["note"]
        assert isinstance(note, str) and note.strip(), (
            f"row {i} ({utterance!r}) has an empty note"
        )


def test_expect_tool_is_a_declared_tool_or_explicitly_null_for_negatives(
    rows: list[dict], declared_tools: set[str]
):
    for row in rows:
        tool = row["expect_tool"]
        if tool is None:
            # A negative row: expect_action must also be null, or the row
            # is claiming a specific action from a tool it says isn't hit.
            assert row["expect_action"] is None, (
                f"row {row['utterance']!r} has expect_tool=None but a "
                f"non-null expect_action={row['expect_action']!r}"
            )
            continue
        assert tool in declared_tools, (
            f"row {row['utterance']!r} expects tool {tool!r}, which is not "
            f"one of this kit's declared tools {sorted(declared_tools)}"
        )


def test_no_duplicate_utterances(rows: list[dict]):
    utterances = [row["utterance"] for row in rows]
    seen: set[str] = set()
    duplicates: list[str] = []
    for u in utterances:
        if u in seen:
            duplicates.append(u)
        seen.add(u)
    assert not duplicates, f"duplicate utterance(s) in golden_matrix.json: {duplicates}"


def test_at_least_five_negative_rows_exist(rows: list[dict]):
    negatives = [r for r in rows if r["expect_tool"] is None]
    assert len(negatives) >= MIN_NEGATIVE_ROWS, (
        f"only {len(negatives)} negative row(s); the order requires at least "
        f"{MIN_NEGATIVE_ROWS} rows that must NOT route to this kit -- a "
        "matrix that only tests success cannot catch over-eager routing"
    )


def test_the_bim_extractor_confusion_is_actually_covered(rows: list[dict]):
    """The order calls out one specific, real confusion by name: quantity
    take-off from an IFC belongs to bim_extractor, not this clash kit, even
    though both blocks accept the same file type. A matrix that dropped this
    row silently would still pass every other check here."""
    hits = [
        r for r in rows
        if "quantit" in r["utterance"].lower() and r["expect_tool"] is None
    ]
    assert hits, (
        "no negative row exercises the IFC-quantity-extraction confusion "
        "with bim_extractor -- see the order's explicit example"
    )


def test_every_positive_row_action_belongs_to_its_tool(matrix: dict, rows: list[dict]):
    """expect_action, when present, must be an action this kit's own
    action->tool map actually assigns to that tool -- catching a row that
    names a real tool but a made-up or mismatched action."""
    kit_json_path = MATRIX_PATH.parents[1] / "kit.json"
    kit = json.loads(kit_json_path.read_text(encoding="utf-8"))
    actions = kit["actions"]
    for row in rows:
        tool = row["expect_tool"]
        action = row["expect_action"]
        if tool is None:
            continue
        assert action in actions, (
            f"row {row['utterance']!r} expects action {action!r}, which is "
            f"not declared in kit.json actions"
        )
        assert actions[action]["tool"] == tool, (
            f"row {row['utterance']!r}: kit.json says action {action!r} "
            f"belongs to tool {actions[action]['tool']!r}, not {tool!r}"
        )
