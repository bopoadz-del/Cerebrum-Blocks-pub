"""Ingestion provenance tests — ported behavior from <private-repo>."""
from __future__ import annotations

import asyncio
import os
import pathlib
import tempfile

os.environ.setdefault("ENV", "test")

from app.blocks.ingestion_provenance import IngestionProvenanceBlock, hash_tree


def _run(coro):
    return asyncio.run(coro)


def test_hash_tree_is_content_stable():
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        (root / "a.txt").write_text("alpha")
        (root / "sub").mkdir()
        (root / "sub" / "b.txt").write_text("beta")
        d1 = hash_tree(td)
        d2 = hash_tree(td)
        assert d1 == d2
        (root / "sub" / "b.txt").write_text("changed")
        assert hash_tree(td) != d1


def test_build_provenance_payload():
    b = IngestionProvenanceBlock()
    r = _run(b.process({"action": "build", "product_id": "p1", "blueprint_id": "b1", "factory_commit": "f1", "blocks_commit": "s1", "plan": {"x": 1}, "inputs_hash": "h1"}))
    assert r["status"] == "ok"
    prov = r["result"]["provenance"]
    assert prov["schema"] == "factory_provenance.v1"
    assert prov["product_id"] == "p1"
    assert prov["blocks_commit"] == "s1"


def test_record_source_labels():
    b = IngestionProvenanceBlock()
    r = _run(b.process({"action": "record_source", "source": "boq.xlsx", "sheet": "Sheet1", "row_start": 2, "row_end": 9}))
    assert r["status"] == "ok"
    assert r["result"]["label"]["sheet"] == "Sheet1"
    labels = _run(b.process({"action": "list_labels"}))
    assert labels["result"]["labels"][0]["source"] == "boq.xlsx"


def test_missing_source_refused():
    b = IngestionProvenanceBlock()
    r = _run(b.process({"action": "record_source"}))
    assert r["status"] == "error"
