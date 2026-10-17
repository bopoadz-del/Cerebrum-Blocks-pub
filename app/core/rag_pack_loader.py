"""Loader and validator for the Prebuilt Domain RAG Pack shelf.

A RAG pack is metadata that describes a prebuilt domain knowledge collection.
It does not contain private enterprise data and it does not perform ingestion.
RAG packs live at ``block_store/shelves/rag_packs.json`` and are consumed by the
factory to know which domain knowledge collections can be attached to a kit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.virgin_shelf import PROJECT_ROOT

_SHELF_REL_PATH = Path("block_store") / "shelves" / "rag_packs.json"

_REQUIRED_PACK_KEYS = {
    "id",
    "domain",
    "name",
    "status",
    "description",
    "collection_id",
    "visibility",
    "data_class",
    "enterprise_specific",
    "requires_blocks",
    "recommended_with_blocks",
    "source_types",
    "expected_queries",
    "expected_outputs",
    "fetch_mode",
    "source_policy",
    "ingestion_status",
    "notes",
}


class RagPackLoaderError(Exception):
    """Raised when the RAG pack shelf cannot be located or parsed."""


class RagPack:
    """Lightweight wrapper around a single domain RAG pack."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @property
    def id(self) -> str:
        return self._data["id"]

    @property
    def domain(self) -> str:
        return self._data["domain"]

    @property
    def name(self) -> str:
        return self._data["name"]

    @property
    def status(self) -> str:
        return self._data["status"]

    @property
    def description(self) -> str:
        return self._data["description"]

    @property
    def collection_id(self) -> str:
        return self._data["collection_id"]

    @property
    def visibility(self) -> str:
        return self._data["visibility"]

    @property
    def data_class(self) -> str:
        return self._data["data_class"]

    @property
    def enterprise_specific(self) -> bool:
        return bool(self._data["enterprise_specific"])

    @property
    def requires_blocks(self) -> list[str]:
        return list(self._data["requires_blocks"])

    @property
    def recommended_with_blocks(self) -> list[str]:
        return list(self._data["recommended_with_blocks"])

    @property
    def source_types(self) -> list[str]:
        return list(self._data["source_types"])

    @property
    def expected_queries(self) -> list[str]:
        return list(self._data["expected_queries"])

    @property
    def expected_outputs(self) -> list[str]:
        return list(self._data["expected_outputs"])

    @property
    def fetch_mode(self) -> str:
        return self._data["fetch_mode"]

    @property
    def source_policy(self) -> dict[str, Any]:
        return dict(self._data["source_policy"])

    @property
    def ingestion_status(self) -> dict[str, Any]:
        return dict(self._data["ingestion_status"])

    @property
    def notes(self) -> list[str]:
        return list(self._data["notes"])

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


def _shelf_path(path: Path | str | None = None) -> Path:
    """Return the absolute path to the RAG pack shelf file."""
    if path:
        return Path(path)
    return PROJECT_ROOT / _SHELF_REL_PATH


def load_shelf(path: Path | str | None = None, *, validate: bool = True) -> dict[str, Any]:
    """Load the RAG pack shelf JSON. Invalid shelves refuse to load (fail closed)."""
    target = Path(path) if path else _shelf_path()
    if not target.exists():
        raise RagPackLoaderError(f"RAG pack shelf not found: {target}")

    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise RagPackLoaderError(f"invalid JSON in RAG pack shelf {target}: {exc}")
    except OSError as exc:
        raise RagPackLoaderError(f"cannot read RAG pack shelf {target}: {exc}")

    if validate:
        errors = _validate_shelf_data(data)
        if errors:
            raise RagPackLoaderError(
                f"invalid RAG pack shelf {target}: {'; '.join(errors)}"
            )
    return data


def list_packs(path: Path | str | None = None) -> list[RagPack]:
    """Return all RAG packs from the shelf."""
    data = load_shelf(path)
    if "packs" not in data:
        raise RagPackLoaderError("RAG pack shelf missing top-level 'packs' key")
    return [RagPack(p) for p in data["packs"]]


def list_domain_ids(path: Path | str | None = None) -> list[str]:
    """Return the sorted list of RAG pack domain ids."""
    return sorted(p.domain for p in list_packs(path))


def get_pack(domain_id: str, path: Path | str | None = None) -> RagPack:
    """Fetch a single RAG pack by domain id."""
    for pack in list_packs(path):
        if pack.domain == domain_id:
            return pack
    raise RagPackLoaderError(f"RAG pack not found for domain: {domain_id}")


def validate_shelf(path: Path | str | None = None) -> list[str]:
    """Validate the entire shelf and return a list of human-readable errors.

    An empty list means the shelf is structurally valid.
    """
    try:
        data = load_shelf(path, validate=False)
    except RagPackLoaderError as exc:
        return [str(exc)]
    return _validate_shelf_data(data)


def _validate_shelf_data(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("shelf_id") != "rag_packs":
        errors.append("shelf_id must be 'rag_packs'")

    for key in ("schema_version", "shelf_id", "name", "description", "packs"):
        if key not in data:
            errors.append(f"shelf missing top-level key: {key}")

    if "packs" not in data:
        return errors

    seen_ids: set[str] = set()
    seen_collection_ids: set[str] = set()
    seen_domains: set[str] = set()

    for idx, pack in enumerate(data["packs"]):
        prefix = f"pack[{idx}]"
        missing = _REQUIRED_PACK_KEYS - set(pack.keys())
        if missing:
            errors.append(f"{prefix} missing keys: {sorted(missing)}")
            continue

        pack_id = pack["id"]
        if pack_id in seen_ids:
            errors.append(f"duplicate pack id: {pack_id}")
        seen_ids.add(pack_id)

        collection_id = pack["collection_id"]
        if collection_id in seen_collection_ids:
            errors.append(f"duplicate collection_id: {collection_id}")
        seen_collection_ids.add(collection_id)

        domain = pack["domain"]
        if domain in seen_domains:
            errors.append(f"duplicate domain: {domain}")
        seen_domains.add(domain)

        for list_key in (
            "requires_blocks",
            "recommended_with_blocks",
            "source_types",
            "expected_queries",
            "expected_outputs",
            "notes",
        ):
            value = pack.get(list_key)
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                errors.append(f"{prefix} '{list_key}' must be a list of strings")

        requires = set(pack.get("requires_blocks", []))
        if "knowledge" not in requires or "vector_search" not in requires:
            errors.append(
                f"{prefix} 'requires_blocks' must include 'knowledge' and 'vector_search'"
            )

        recommended = set(pack.get("recommended_with_blocks", []))
        if f"{domain}_v2" not in recommended or "formula_executor_v2" not in recommended:
            errors.append(
                f"{prefix} 'recommended_with_blocks' must include '{domain}_v2' and 'formula_executor_v2'"
            )

        if pack.get("fetch_mode") != "metadata_only":
            errors.append(f"{prefix} 'fetch_mode' must be 'metadata_only'")

        source_policy = pack.get("source_policy")
        if not isinstance(source_policy, dict):
            errors.append(f"{prefix} 'source_policy' must be an object")
        else:
            for key in (
                "allowed_source_classes",
                "precluded_source_classes",
                "requires_source_record",
                "requires_license_review",
                "requires_authority_rating",
            ):
                if key not in source_policy:
                    errors.append(f"{prefix} 'source_policy' missing '{key}'")

            if source_policy.get("requires_source_record") is not True:
                errors.append(f"{prefix} 'source_policy.requires_source_record' must be true")
            if source_policy.get("requires_license_review") is not True:
                errors.append(f"{prefix} 'source_policy.requires_license_review' must be true")
            if source_policy.get("requires_authority_rating") is not True:
                errors.append(f"{prefix} 'source_policy.requires_authority_rating' must be true")

            allowed = source_policy.get("allowed_source_classes", [])
            if not isinstance(allowed, list) or len(allowed) == 0:
                errors.append(f"{prefix} 'source_policy.allowed_source_classes' must be a non-empty list")

            precluded = set(source_policy.get("precluded_source_classes", []))
            for required_precluded in (
                "private_enterprise_data",
                "confidential_client_data",
                "unknown_license",
            ):
                if required_precluded not in precluded:
                    errors.append(
                        f"{prefix} 'source_policy.precluded_source_classes' must include '{required_precluded}'"
                    )

        ingestion_status = pack.get("ingestion_status")
        if not isinstance(ingestion_status, dict):
            errors.append(f"{prefix} 'ingestion_status' must be an object")
        else:
            if ingestion_status.get("state") != "not_ingested":
                errors.append(f"{prefix} 'ingestion_status.state' must be 'not_ingested'")
            for key in ("documents_total", "documents_indexed", "chunks_total"):
                if ingestion_status.get(key) != 0:
                    errors.append(f"{prefix} 'ingestion_status.{key}' must be 0")
            if ingestion_status.get("last_ingested_at") is not None:
                errors.append(f"{prefix} 'ingestion_status.last_ingested_at' must be null")
            if ingestion_status.get("last_error") is not None:
                errors.append(f"{prefix} 'ingestion_status.last_error' must be null")

        if pack.get("enterprise_specific") is not False:
            errors.append(f"{prefix} 'enterprise_specific' must be false")

    return errors
