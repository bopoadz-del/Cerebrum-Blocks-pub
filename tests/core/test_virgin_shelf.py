"""Tests for the Domain Virgin Edition manifest shelf loader/validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.virgin_shelf import (
    VirginShelfError,
    get_edition,
    list_domain_ids,
    list_editions,
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
    assert data["shelf_id"] == "virgin_domains"
    assert "schema_version" in data
    assert "editions" in data
    assert len(data["editions"]) == 17


def test_list_domain_ids_covers_all_17_domains():
    domains = list_domain_ids()
    assert domains == _EXPECTED_DOMAINS


def test_each_edition_has_required_fields():
    for edition in list_editions():
        assert edition.id
        assert edition.name
        assert edition.domain
        assert edition.version
        assert edition.container_class
        assert edition.blocks
        assert edition.source_kit
        assert edition.description


def test_each_edition_contains_base_blocks_and_one_domain_block():
    for edition in list_editions():
        blocks = set(edition.blocks)
        assert {"pdf", "ocr", "chat", "image"}.issubset(blocks)
        domain_block = edition.domain_v2_block
        assert domain_block.endswith("_v2")
        assert domain_block == f"{edition.domain}_v2" or (
            edition.domain == "hotel_management" and domain_block == "hotel_management_v2"
        )


def test_get_edition_for_each_domain():
    for domain_id in _EXPECTED_DOMAINS:
        edition = get_edition(domain_id)
        assert edition.id == domain_id


def test_get_edition_missing_raises():
    with pytest.raises(VirginShelfError):
        get_edition("not_a_domain")


def test_validate_shelf_reports_no_errors():
    errors = validate_shelf()
    assert errors == []


def test_validate_shelf_detects_missing_base_block(tmp_path: Path):
    bad_shelf = tmp_path / "bad_shelf.json"
    bad_shelf.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "shelf_id": "bad",
                "name": "Bad Shelf",
                "description": "test",
                "editions": [
                    {
                        "id": "bad",
                        "name": "Bad",
                        "domain": "bad",
                        "version": "1.0.0",
                        "container_class": "app.containers.bad.BadContainer",
                        "blocks": ["pdf", "ocr", "chat", "bad_v2"],
                        "source_kit": "block_store/kits/bad/manifest.json",
                        "description": "missing image",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_shelf(bad_shelf)
    assert any("missing base blocks" in e for e in errors)


def test_validate_shelf_detects_duplicate_id(tmp_path: Path):
    bad_shelf = tmp_path / "bad_shelf.json"
    edition = {
        "id": "legal",
        "name": "Legal",
        "domain": "legal",
        "version": "1.0.0",
        "container_class": "app.containers.legal.LegalContainer",
        "blocks": ["pdf", "ocr", "chat", "image", "legal_v2"],
        "source_kit": "block_store/kits/legal/manifest.json",
        "description": "dup",
    }
    bad_shelf.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "shelf_id": "dup",
                "name": "Dup Shelf",
                "description": "test",
                "editions": [edition, edition],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_shelf(bad_shelf)
    assert any("duplicate edition id" in e for e in errors)


def test_validate_shelf_detects_missing_source_kit(tmp_path: Path):
    bad_shelf = tmp_path / "bad_shelf.json"
    bad_shelf.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "shelf_id": "missing_kit",
                "name": "Missing Kit Shelf",
                "description": "test",
                "editions": [
                    {
                        "id": "ghost",
                        "name": "Ghost",
                        "domain": "ghost",
                        "version": "1.0.0",
                        "container_class": "app.containers.ghost.GhostContainer",
                        "blocks": ["pdf", "ocr", "chat", "image", "ghost_v2"],
                        "source_kit": "block_store/kits/ghost/manifest.json",
                        "description": "missing kit",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_shelf(bad_shelf)
    assert any("source_kit not found" in e for e in errors)


def test_load_shelf_fails_closed_on_invalid_shelf(tmp_path: Path):
    """An invalid shelf must refuse to load, not merely report when asked."""
    bad_shelf = tmp_path / "bad_shelf.json"
    bad_shelf.write_text(
        json.dumps({"schema_version": "1.0.0", "shelf_id": "bad"}),
        encoding="utf-8",
    )
    with pytest.raises(VirginShelfError):
        load_shelf(bad_shelf)
