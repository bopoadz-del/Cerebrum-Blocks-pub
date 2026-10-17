"""Loader and validator for the Domain Virgin Edition manifest shelf.

A Virgin Edition is the minimal clean domain kit: one DomainContainer, the four
base interface/parser blocks (pdf, ocr, chat, image), and one domain v2 block.
The shelf lives at ``block_store/shelves/virgin_domains.json`` and is consumed
by the store/factory to advertise domain offerings without pulling in extended
platform blocks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHELF_PATH = PROJECT_ROOT / "block_store" / "shelves" / "virgin_domains.json"

_BASE_BLOCKS = {"pdf", "ocr", "chat", "image"}
_REQUIRED_EDITION_KEYS = {
    "id",
    "name",
    "domain",
    "version",
    "container_class",
    "blocks",
    "source_kit",
    "description",
}


class VirginShelfError(ValueError):
    """Raised when the virgin shelf is missing or invalid."""


class VirginEdition:
    """Lightweight wrapper around a single virgin edition manifest."""

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
    def version(self) -> str:
        return self._data["version"]

    @property
    def container_class(self) -> str:
        return self._data["container_class"]

    @property
    def blocks(self) -> list[str]:
        return list(self._data["blocks"])

    @property
    def source_kit(self) -> str:
        return self._data["source_kit"]

    @property
    def description(self) -> str:
        return self._data["description"]

    @property
    def domain_v2_block(self) -> str:
        """Return the domain-specific *_v2 block id."""
        domain_blocks = set(self.blocks) - _BASE_BLOCKS
        if len(domain_blocks) != 1:
            raise VirginShelfError(
                f"edition '{self.id}' must contain exactly one domain block "
                f"beyond the base four; got {sorted(domain_blocks)}"
            )
        return domain_blocks.pop()

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


def load_shelf(path: Path | str | None = None, *, validate: bool = True) -> dict[str, Any]:
    """Load the virgin shelf JSON. Invalid shelves refuse to load (fail closed)."""
    target = Path(path) if path else SHELF_PATH
    if not target.exists():
        raise VirginShelfError(f"virgin shelf not found: {target}")
    with open(target, encoding="utf-8") as f:
        data = json.load(f)
    if validate:
        errors = _validate_shelf_data(data)
        if errors:
            raise VirginShelfError(
                f"invalid virgin shelf {target}: {'; '.join(errors)}"
            )
    return data


def list_editions(path: Path | str | None = None) -> list[VirginEdition]:
    """Return all virgin editions from the shelf."""
    data = load_shelf(path)
    if "editions" not in data:
        raise VirginShelfError("virgin shelf missing top-level 'editions' key")
    return [VirginEdition(ed) for ed in data["editions"]]


def list_domain_ids(path: Path | str | None = None) -> list[str]:
    """Return the sorted list of virgin edition domain ids."""
    return sorted(ed.id for ed in list_editions(path))


def get_edition(domain_id: str, path: Path | str | None = None) -> VirginEdition:
    """Fetch a single virgin edition by domain id."""
    for edition in list_editions(path):
        if edition.id == domain_id:
            return edition
    raise VirginShelfError(f"virgin edition not found for domain: {domain_id}")


def validate_shelf(path: Path | str | None = None) -> list[str]:
    """Validate the entire shelf and return a list of human-readable errors.

    An empty list means the shelf is structurally valid.
    """
    try:
        data = load_shelf(path, validate=False)
    except VirginShelfError as exc:
        return [str(exc)]
    return _validate_shelf_data(data)


def _validate_shelf_data(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("schema_version", "shelf_id", "name", "description", "editions"):
        if key not in data:
            errors.append(f"shelf missing top-level key: {key}")

    if "editions" not in data:
        return errors

    seen_ids: set[str] = set()
    for idx, edition in enumerate(data["editions"]):
        prefix = f"edition[{idx}]"
        missing = _REQUIRED_EDITION_KEYS - set(edition.keys())
        if missing:
            errors.append(f"{prefix} missing keys: {sorted(missing)}")
            continue

        if edition["id"] in seen_ids:
            errors.append(f"duplicate edition id: {edition['id']}")
        seen_ids.add(edition["id"])

        blocks = set(edition["blocks"])
        if not _BASE_BLOCKS.issubset(blocks):
            missing_base = _BASE_BLOCKS - blocks
            errors.append(
                f"{prefix} ('{edition['id']}') missing base blocks: {sorted(missing_base)}"
            )

        domain_blocks = blocks - _BASE_BLOCKS
        if len(domain_blocks) != 1:
            errors.append(
                f"{prefix} ('{edition['id']}') must have exactly one domain block; "
                f"got {sorted(domain_blocks)}"
            )

        kit_path = PROJECT_ROOT / edition["source_kit"]
        if not kit_path.exists():
            errors.append(f"{prefix} source_kit not found: {edition['source_kit']}")

        container_class = edition.get("container_class", "")
        if not container_class or "." not in container_class:
            errors.append(f"{prefix} invalid container_class: {container_class}")

    return errors
