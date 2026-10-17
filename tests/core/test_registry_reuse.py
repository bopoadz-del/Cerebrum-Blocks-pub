"""Exact-id REUSE present? lookup — Factory STEP 0 inventory surface."""

from __future__ import annotations

from app.block_registry import registry_block_exists, registry_reuse_lookup


def test_an_exact_registry_id_is_present_with_manifest_fields():
    result = registry_reuse_lookup("document_engine")
    assert result["present"] is True
    assert result["reuse"] is True
    assert result["id"] == "document_engine"
    assert result["source"] == "registry"
    assert "manifest" in result
    assert result["manifest"]["id"] == "document_engine"
    for field in ("reads", "writes", "never", "acceptance"):
        assert field in result
        assert isinstance(result[field], list)
        assert field in result["manifest"]


def test_an_unknown_id_is_a_negative_lookup_not_a_guess():
    result = registry_reuse_lookup("definitely_not_a_registered_block")
    assert result == {
        "present": False,
        "id": "definitely_not_a_registered_block",
        "reuse": False,
    }


def test_lookup_is_exact_id_not_a_prefix_or_alias():
    assert registry_block_exists("pdf")
    # Nearby / case-shifted ids must not resolve. Inventory is a registry
    # query, not a guess.
    assert registry_reuse_lookup("PDF")["present"] is False
    assert registry_reuse_lookup("pdf_block")["present"] is False
    assert registry_reuse_lookup("pd")["present"] is False


def test_path_shaped_ids_are_rejected():
    assert registry_reuse_lookup("../pdf")["present"] is False
    assert registry_reuse_lookup("foo/bar")["present"] is False
    assert registry_reuse_lookup("")["present"] is False
