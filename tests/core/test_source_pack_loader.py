"""Tests for the Domain Source Pack shelf loader/validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.source_pack_loader import (
    SourcePackError,
    get_pack,
    list_domain_ids,
    list_packs,
    load_shelf,
    validate_shelf,
)


_EXPECTED_DOMAINS = [
    "agriculture",
    "automotive",
    "aviation",
    "construction",
    "education",
    "finance",
    "hotel_management",
    "hr",
    "insurance",
    "legal",
    "manufacturing",
    "medical",
    "oil_gas",
    "pharma",
    "real_estate",
    "retail",
    "supply_chain",
]


def test_load_shelf_returns_expected_shape():
    data = load_shelf()
    assert data["shelf_id"] == "source_packs"
    assert "schema_version" in data
    assert "packs" in data
    assert len(data["packs"]) == 17


def test_list_domain_ids_covers_all_17_domains():
    domains = list_domain_ids()
    assert domains == _EXPECTED_DOMAINS


def test_each_pack_has_required_fields():
    for pack in list_packs():
        assert pack.id
        assert pack.name
        assert pack.domain
        assert pack.description
        assert pack.expert_prompt
        assert pack.workflow
        assert pack.use_cases
        assert pack.example_prompts
        assert pack.expected_inputs
        assert pack.expected_outputs
        assert pack.blocks


def test_each_pack_has_valid_block_lists():
    base = {"pdf", "ocr", "chat", "image"}
    for pack in list_packs():
        blocks = set(pack.blocks)
        assert base.issubset(blocks), f"{pack.id} missing base blocks"
        assert "formula_executor_v2" in blocks, f"{pack.id} missing shared formula_executor_v2"
        domain_blocks = blocks - base - {"formula_executor_v2"}
        assert len(domain_blocks) == 1, f"{pack.id} must have exactly one domain block"
        assert pack.id in domain_blocks.pop(), f"{pack.id} domain block mismatch"


def test_get_pack_for_each_domain():
    for domain_id in _EXPECTED_DOMAINS:
        pack = get_pack(domain_id)
        assert pack.id == domain_id


def test_get_pack_missing_raises():
    with pytest.raises(SourcePackError):
        get_pack("not_a_domain")


def test_validate_shelf_reports_no_errors():
    errors = validate_shelf()
    assert errors == []


def test_validate_shelf_detects_missing_key(tmp_path: Path):
    bad_shelf = tmp_path / "bad_shelf.json"
    bad_shelf.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "shelf_id": "bad",
                "name": "Bad Shelf",
                "description": "test",
                "packs": [
                    {
                        "id": "bad",
                        "domain": "bad",
                        "name": "Bad",
                        "description": "missing expert_prompt",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_shelf(bad_shelf)
    assert any("missing keys" in e for e in errors)


def test_validate_shelf_detects_duplicate_id(tmp_path: Path):
    bad_shelf = tmp_path / "bad_shelf.json"
    pack = {
        "id": "legal",
        "domain": "legal",
        "name": "Legal",
        "description": "test",
        "expert_prompt": "You are a legal expert.",
        "workflow": "test",
        "use_cases": ["test"],
        "example_prompts": ["test"],
        "expected_inputs": ["test"],
        "expected_outputs": ["test"],
        "blocks": ["pdf", "ocr", "chat", "image", "legal_v2"],
    }
    bad_shelf.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "shelf_id": "dup",
                "name": "Dup Shelf",
                "description": "test",
                "packs": [pack, pack],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_shelf(bad_shelf)
    assert any("duplicate pack id" in e for e in errors)


def test_validate_shelf_detects_invalid_list_field(tmp_path: Path):
    bad_shelf = tmp_path / "bad_shelf.json"
    bad_shelf.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "shelf_id": "bad",
                "name": "Bad Shelf",
                "description": "test",
                "packs": [
                    {
                        "id": "bad",
                        "domain": "bad",
                        "name": "Bad",
                        "description": "test",
                        "expert_prompt": "You are bad.",
                        "workflow": "test",
                        "use_cases": "not a list",
                        "example_prompts": ["test"],
                        "expected_inputs": ["test"],
                        "expected_outputs": ["test"],
                        "blocks": ["pdf", "ocr", "chat", "image", "bad_v2"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_shelf(bad_shelf)
    assert any("must be a list of strings" in e for e in errors)


def test_load_shelf_fails_closed_on_invalid_shelf(tmp_path: Path):
    """An invalid shelf must refuse to load, not merely report when asked."""
    bad_shelf = tmp_path / "bad_shelf.json"
    bad_shelf.write_text(
        json.dumps({"schema_version": "1.0.0", "shelf_id": "bad"}),
        encoding="utf-8",
    )
    with pytest.raises(SourcePackError):
        load_shelf(bad_shelf)
