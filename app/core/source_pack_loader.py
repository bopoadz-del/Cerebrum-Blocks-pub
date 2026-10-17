"""Loader and validator for the Domain Source Pack shelf.

A source pack is metadata that describes what a Domain Virgin Edition does, how
it should answer, what inputs it expects, what outputs it produces, and which
blocks form a minimal useful chain. Source packs live at
``block_store/shelves/source_packs.json`` and are consumed by the factory chain
generator. No documents are ingested here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.virgin_shelf import PROJECT_ROOT

SHELF_PATH = PROJECT_ROOT / "block_store" / "shelves" / "source_packs.json"

_REQUIRED_PACK_KEYS = {
    "id",
    "domain",
    "name",
    "description",
    "expert_prompt",
    "workflow",
    "use_cases",
    "example_prompts",
    "expected_inputs",
    "expected_outputs",
    "blocks",
}


class SourcePackError(ValueError):
    """Raised when the source pack shelf is missing or invalid."""


class SourcePack:
    """Lightweight wrapper around a single domain source pack."""

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
    def description(self) -> str:
        return self._data["description"]

    @property
    def expert_prompt(self) -> str:
        return self._data["expert_prompt"]

    @property
    def workflow(self) -> str:
        return self._data["workflow"]

    @property
    def use_cases(self) -> list[str]:
        return list(self._data["use_cases"])

    @property
    def example_prompts(self) -> list[str]:
        return list(self._data["example_prompts"])

    @property
    def expected_inputs(self) -> list[str]:
        return list(self._data["expected_inputs"])

    @property
    def expected_outputs(self) -> list[str]:
        return list(self._data["expected_outputs"])

    @property
    def blocks(self) -> list[str]:
        return list(self._data["blocks"])

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


def load_shelf(path: Path | str | None = None, *, validate: bool = True) -> dict[str, Any]:
    """Load the source pack shelf JSON. Invalid shelves refuse to load (fail closed)."""
    target = Path(path) if path else SHELF_PATH
    if not target.exists():
        raise SourcePackError(f"source pack shelf not found: {target}")

    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise SourcePackError(f"invalid JSON in source pack shelf {target}: {exc}")
    except OSError as exc:
        raise SourcePackError(f"cannot read source pack shelf {target}: {exc}")

    if validate:
        errors = _validate_shelf_data(data)
        if errors:
            raise SourcePackError(
                f"invalid source pack shelf {target}: {'; '.join(errors)}"
            )
    return data


def list_packs(path: Path | str | None = None) -> list[SourcePack]:
    """Return all source packs from the shelf."""
    data = load_shelf(path)
    if "packs" not in data:
        raise SourcePackError("source pack shelf missing top-level 'packs' key")
    return [SourcePack(p) for p in data["packs"]]


def list_domain_ids(path: Path | str | None = None) -> list[str]:
    """Return the sorted list of source pack domain ids."""
    return sorted(p.id for p in list_packs(path))


def get_pack(domain_id: str, path: Path | str | None = None) -> SourcePack:
    """Fetch a single source pack by domain id."""
    for pack in list_packs(path):
        if pack.id == domain_id:
            return pack
    raise SourcePackError(f"source pack not found for domain: {domain_id}")


def validate_shelf(path: Path | str | None = None) -> list[str]:
    """Validate the entire shelf and return a list of human-readable errors.

    An empty list means the shelf is structurally valid.
    """
    try:
        data = load_shelf(path, validate=False)
    except SourcePackError as exc:
        return [str(exc)]
    return _validate_shelf_data(data)


def _validate_shelf_data(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("schema_version", "shelf_id", "name", "description", "packs"):
        if key not in data:
            errors.append(f"shelf missing top-level key: {key}")

    if "packs" not in data:
        return errors

    seen_ids: set[str] = set()
    for idx, pack in enumerate(data["packs"]):
        prefix = f"pack[{idx}]"
        missing = _REQUIRED_PACK_KEYS - set(pack.keys())
        if missing:
            errors.append(f"{prefix} missing keys: {sorted(missing)}")
            continue

        if pack["id"] in seen_ids:
            errors.append(f"duplicate pack id: {pack['id']}")
        seen_ids.add(pack["id"])

        for list_key in (
            "use_cases",
            "example_prompts",
            "expected_inputs",
            "expected_outputs",
            "blocks",
        ):
            value = pack.get(list_key)
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                errors.append(f"{prefix} '{list_key}' must be a list of strings")

        if not isinstance(pack.get("expert_prompt"), str) or not pack["expert_prompt"]:
            errors.append(f"{prefix} 'expert_prompt' must be a non-empty string")

    return errors
