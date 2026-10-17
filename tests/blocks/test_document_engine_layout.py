"""Lock the document_engine wrapper layout for Store vendoring.

The ``document_engine/`` package shadows ``app/blocks/document_engine.py``.
Factory CLONER scans ``app.blocks.(\\w+)`` and requires
``app/blocks/document_engine_block.py`` (or a package of that name) on disk.
"""

import secrets
import sys
from pathlib import Path

from app.blocks import get_block
from app.blocks.document_engine import DocumentEngineBlock as PackageBlock
from app.blocks.document_engine_block import DocumentEngineBlock as FileBlock
from app.core.universal_base import UniversalBlock

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER_PATH = _REPO_ROOT / "app" / "blocks" / "document_engine_block.py"


def test_document_engine_block_module_exists_on_disk():
    assert _WRAPPER_PATH.is_file(), (
        "runtime slice needs app/blocks/document_engine_block.py"
    )


def test_document_engine_block_importable_via_package_and_module():
    assert PackageBlock is FileBlock
    assert issubclass(PackageBlock, UniversalBlock)
    assert PackageBlock.__name__ == "DocumentEngineBlock"
    assert getattr(PackageBlock, "name", None) == "document_engine"


def test_get_block_document_engine_returns_wrapper():
    cls = get_block("document_engine")
    assert cls is PackageBlock
    assert cls is FileBlock


def test_package_import_does_not_shadow_stdlib_secrets():
    """Importing the package must not put app/blocks on sys.path.

    That shadow made ``from secrets import token_hex`` load
    ``app/blocks/secrets.py`` and broke FastAPI collection in the full suite.
    """
    blocks_dir = (_REPO_ROOT / "app" / "blocks").resolve()
    polluted = [
        Path(entry).resolve()
        for entry in sys.path
        if entry and Path(entry).resolve() == blocks_dir
    ]
    assert not polluted, f"app/blocks leaked onto sys.path: {polluted}"
    assert hasattr(secrets, "token_hex")
    assert Path(secrets.__file__).resolve() != (blocks_dir / "secrets.py").resolve()
