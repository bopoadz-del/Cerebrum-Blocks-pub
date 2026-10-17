"""Tests for the Prebuilt Domain RAG Pack shelf loader/validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.rag_pack_loader import (
    RagPackLoaderError,
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
    assert data["shelf_id"] == "rag_packs"
    assert "schema_version" in data
    assert "packs" in data
    assert len(data["packs"]) == 17


def test_list_domain_ids_covers_all_17_domains():
    domains = list_domain_ids()
    assert domains == _EXPECTED_DOMAINS


def test_each_pack_has_required_fields():
    for pack in list_packs():
        assert pack.id
        assert pack.domain
        assert pack.name
        assert pack.status
        assert pack.description
        assert pack.collection_id
        assert pack.visibility
        assert pack.data_class
        assert isinstance(pack.enterprise_specific, bool)
        assert pack.requires_blocks
        assert pack.recommended_with_blocks
        assert pack.source_types
        assert isinstance(pack.expected_queries, list)
        assert isinstance(pack.expected_outputs, list)
        assert pack.fetch_mode
        assert pack.ingestion_status
        assert isinstance(pack.notes, list)


def test_each_pack_requires_knowledge_and_vector_search():
    for pack in list_packs():
        requires = set(pack.requires_blocks)
        assert "knowledge" in requires, f"{pack.id} missing knowledge"
        assert "vector_search" in requires, f"{pack.id} missing vector_search"


def test_each_pack_recommends_domain_v2_and_formula_executor():
    for pack in list_packs():
        recommended = set(pack.recommended_with_blocks)
        expected_domain_v2 = f"{pack.domain}_v2"
        assert expected_domain_v2 in recommended, f"{pack.id} missing {expected_domain_v2}"
        assert "formula_executor_v2" in recommended, f"{pack.id} missing formula_executor_v2"


def test_each_pack_is_metadata_only_and_not_ingested():
    for pack in list_packs():
        assert pack.fetch_mode == "metadata_only", f"{pack.id} fetch_mode mismatch"
        assert isinstance(pack.ingestion_status, dict), f"{pack.id} ingestion_status must be an object"
        assert pack.ingestion_status["state"] == "not_ingested", f"{pack.id} ingestion_status.state mismatch"
        assert pack.ingestion_status["documents_total"] == 0, f"{pack.id} documents_total must be 0"
        assert pack.ingestion_status["documents_indexed"] == 0, f"{pack.id} documents_indexed must be 0"
        assert pack.ingestion_status["chunks_total"] == 0, f"{pack.id} chunks_total must be 0"
        assert pack.ingestion_status["last_ingested_at"] is None, f"{pack.id} last_ingested_at must be null"
        assert pack.ingestion_status["last_error"] is None, f"{pack.id} last_error must be null"
        assert pack.enterprise_specific is False, f"{pack.id} enterprise_specific must be false"


def test_each_pack_has_source_policy():
    for pack in list_packs():
        assert isinstance(pack.source_policy, dict), f"{pack.id} source_policy must be an object"
        assert pack.source_policy.get("requires_source_record") is True
        assert pack.source_policy.get("requires_license_review") is True
        assert pack.source_policy.get("requires_authority_rating") is True
        allowed = pack.source_policy.get("allowed_source_classes", [])
        assert isinstance(allowed, list) and len(allowed) > 0
        precluded = set(pack.source_policy.get("precluded_source_classes", []))
        assert "private_enterprise_data" in precluded
        assert "confidential_client_data" in precluded
        assert "unknown_license" in precluded


def test_legal_core_rag_has_expected_new_shape():
    pack = get_pack("legal")
    assert pack.id == "legal_core_rag"
    assert pack.source_policy["requires_source_record"] is True
    assert pack.ingestion_status["state"] == "not_ingested"
    assert pack.ingestion_status["documents_total"] == 0


#: The corpus the aviation pack points at. It has never been committed --
#: `git ls-files` finds nothing under this name -- and the largest member is
#: a multi-megabyte FAA PDF, so it is a fetched artifact rather than a
#: tracked one.
AVIATION_CORPUS_FILES = {
    "AIM_Basic_w_Chg_1_2_3_dtd_7-9-26.pdf",
    "aim_index.html",
    "cfr_part_121.xml",
    "cfr_part_135.xml",
    "cfr_part_61.xml",
    "cfr_part_91.xml",
}


def _aviation_corpus_dir():
    return (
        Path(__file__).resolve().parents[2]
        / "block_store"
        / "kits"
        / "aviation_faa_core_rag"
    )


def test_the_aviation_pack_points_somewhere_specific():
    """Runs everywhere. The metadata half of the old test.

    Split out because the other half asserted a directory that is not in the
    repository, so the whole test failed for a reason that had nothing to do
    with the pack's metadata -- and it failed unseen, being one of the 103
    files CI never ran.
    """
    pack = get_pack("aviation")
    assert pack.id == "aviation_core_rag"
    assert pack.domain == "aviation"


def test_aviation_core_rag_source_documents_exist():
    """The corpus itself, when it has been fetched.

    Skipped rather than failed when absent: the pack declaring a corpus that
    is not in the repository is a real gap, recorded in KNOWN_INCOMPLETE.md,
    but it is a gap in the corpus rather than a regression in this code, and
    a permanently-red test teaches people to ignore red.
    """
    source_dir = _aviation_corpus_dir()
    if not source_dir.is_dir():
        pytest.skip(
            f"aviation source corpus not present at {source_dir}. It has never "
            f"been committed (see KNOWN_INCOMPLETE.md); fetch it to run this."
        )

    expected_files = {
        "AIM_Basic_w_Chg_1_2_3_dtd_7-9-26.pdf",
        "aim_index.html",
        "cfr_part_121.xml",
        "cfr_part_135.xml",
        "cfr_part_61.xml",
        "cfr_part_91.xml",
    }
    found_files = {p.name for p in source_dir.iterdir() if p.is_file()}
    assert expected_files <= found_files, (
        f"aviation corpus missing expected files: {expected_files - found_files}"
    )

    # Every source file must be non-empty; the PDF is the largest reference.
    for name in expected_files:
        path = source_dir / name
        assert path.stat().st_size > 0, f"aviation corpus file is empty: {name}"


def test_pack_collection_ids_are_unique():
    collection_ids = [pack.collection_id for pack in list_packs()]
    assert len(collection_ids) == len(set(collection_ids))


def test_get_pack_for_legal_returns_legal_core_rag():
    pack = get_pack("legal")
    assert pack.id == "legal_core_rag"
    assert pack.domain == "legal"


def test_get_pack_missing_raises():
    with pytest.raises(RagPackLoaderError):
        get_pack("not_a_domain")


def test_validate_shelf_reports_no_errors():
    errors = validate_shelf()
    assert errors == []


def test_validate_shelf_detects_wrong_shelf_id(tmp_path: Path):
    bad_shelf = tmp_path / "bad_shelf.json"
    bad_shelf.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "shelf_id": "wrong",
                "name": "Wrong Shelf",
                "description": "test",
                "packs": [],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_shelf(bad_shelf)
    assert any("shelf_id" in e for e in errors)


def test_validate_shelf_detects_missing_required_key(tmp_path: Path):
    bad_shelf = tmp_path / "bad_shelf.json"
    bad_shelf.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "shelf_id": "rag_packs",
                "name": "Bad Shelf",
                "description": "test",
                "packs": [
                    {
                        "id": "bad_core_rag",
                        "domain": "bad",
                        "name": "Bad",
                        "description": "test",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_shelf(bad_shelf)
    assert any("missing keys" in e for e in errors)


def test_validate_shelf_detects_missing_knowledge_block(tmp_path: Path):
    bad_shelf = tmp_path / "bad_shelf.json"
    bad_shelf.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "shelf_id": "rag_packs",
                "name": "Bad Shelf",
                "description": "test",
                "packs": [
                    _make_bad_pack(requires_blocks=["vector_search"])
                ],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_shelf(bad_shelf)
    assert any("'knowledge' and 'vector_search'" in e for e in errors)


def test_validate_shelf_detects_enterprise_specific_true(tmp_path: Path):
    bad_shelf = tmp_path / "bad_shelf.json"
    bad_shelf.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "shelf_id": "rag_packs",
                "name": "Bad Shelf",
                "description": "test",
                "packs": [
                    _make_bad_pack(enterprise_specific=True)
                ],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_shelf(bad_shelf)
    assert any("enterprise_specific" in e for e in errors)


def test_validate_shelf_detects_string_ingestion_status(tmp_path: Path):
    bad_shelf = tmp_path / "bad_shelf.json"
    bad_shelf.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "shelf_id": "rag_packs",
                "name": "Bad Shelf",
                "description": "test",
                "packs": [
                    _make_bad_pack(ingestion_status="ingested")
                ],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_shelf(bad_shelf)
    assert any("'ingestion_status' must be an object" in e for e in errors)


def test_validate_shelf_detects_missing_source_policy(tmp_path: Path):
    bad_shelf = tmp_path / "bad_shelf.json"
    pack = _make_bad_pack()
    del pack["source_policy"]
    bad_shelf.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "shelf_id": "rag_packs",
                "name": "Bad Shelf",
                "description": "test",
                "packs": [pack],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_shelf(bad_shelf)
    assert any("missing keys" in e and "source_policy" in e for e in errors)


def test_validate_shelf_detects_bad_source_policy(tmp_path: Path):
    bad_shelf = tmp_path / "bad_shelf.json"
    bad_shelf.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "shelf_id": "rag_packs",
                "name": "Bad Shelf",
                "description": "test",
                "packs": [
                    _make_bad_pack(
                        source_policy={
                            "allowed_source_classes": [],
                            "precluded_source_classes": ["private_enterprise_data"],
                            "requires_source_record": False,
                            "requires_license_review": False,
                            "requires_authority_rating": False,
                        }
                    )
                ],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_shelf(bad_shelf)
    assert any("requires_source_record" in e for e in errors)
    assert any("requires_license_review" in e for e in errors)
    assert any("requires_authority_rating" in e for e in errors)
    assert any("allowed_source_classes" in e for e in errors)
    assert any("confidential_client_data" in e for e in errors)
    assert any("unknown_license" in e for e in errors)


def _make_bad_pack(**overrides):
    pack = {
        "id": "bad_core_rag",
        "domain": "bad",
        "name": "Bad",
        "description": "test",
        "status": "metadata_only",
        "collection_id": "prebuilt_bad_core",
        "visibility": "platform_prebuilt",
        "data_class": "public_or_licensed_reference",
        "enterprise_specific": False,
        "requires_blocks": ["knowledge", "vector_search"],
        "recommended_with_blocks": ["bad_v2", "formula_executor_v2"],
        "source_types": ["guidance"],
        "expected_queries": [],
        "expected_outputs": [],
        "fetch_mode": "metadata_only",
        "source_policy": {
            "allowed_source_classes": ["official_guidance"],
            "precluded_source_classes": [
                "private_enterprise_data",
                "confidential_client_data",
                "copyrighted_commercial_content_without_license",
                "user_uploaded_project_records",
                "unknown_license",
            ],
            "requires_source_record": True,
            "requires_license_review": True,
            "requires_authority_rating": True,
        },
        "ingestion_status": {
            "state": "not_ingested",
            "documents_total": 0,
            "documents_indexed": 0,
            "chunks_total": 0,
            "last_ingested_at": None,
            "last_error": None,
        },
        "notes": [],
    }
    pack.update(overrides)
    return pack


def test_load_shelf_fails_closed_on_invalid_shelf(tmp_path: Path):
    """An invalid shelf must refuse to load, not merely report when asked."""
    bad_shelf = tmp_path / "bad_shelf.json"
    bad_shelf.write_text(
        json.dumps({"schema_version": "1.0.0", "shelf_id": "bad"}),
        encoding="utf-8",
    )
    with pytest.raises(RagPackLoaderError):
        load_shelf(bad_shelf)
