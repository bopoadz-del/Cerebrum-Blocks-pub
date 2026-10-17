"""Document Engine block for Cerebrum-Blocks.

Provides Parse → Reason → Map pipeline for technical document intelligence.
"""
import importlib.util
import os
import sys
from .main import main, parse_all
from .reasoner import DocumentReasoner, ReasonedOutput
from .mapper import DocumentMapper, StructuredDocument

# The document_engine/ package shadows app/blocks/document_engine.py for
# ``import app.blocks.document_engine``. The platform wrapper lives in
# document_engine_block.py so factory CLONER / runtime-slice scanners that
# resolve app.blocks.(\w+) find an on-disk module. Load it explicitly and
# register it in sys.modules so ``import app.blocks.document_engine_block``
# and this re-export share one class object.

_BLOCK_MODULE_NAME = "app.blocks.document_engine_block"
_BLOCK_FILE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "document_engine_block.py")
)
if _BLOCK_MODULE_NAME in sys.modules:
    _block_module = sys.modules[_BLOCK_MODULE_NAME]
else:
    _spec = importlib.util.spec_from_file_location(_BLOCK_MODULE_NAME, _BLOCK_FILE_PATH)
    if _spec is None or _spec.loader is None:
        raise ImportError(
            f"document_engine wrapper missing at {_BLOCK_FILE_PATH}"
        )
    _block_module = importlib.util.module_from_spec(_spec)
    sys.modules[_BLOCK_MODULE_NAME] = _block_module
    _spec.loader.exec_module(_block_module)
DocumentEngineBlock = _block_module.DocumentEngineBlock

__all__ = [
    "main",
    "parse_all",
    "DocumentReasoner",
    "ReasonedOutput",
    "DocumentMapper",
    "StructuredDocument",
    "DocumentEngineBlock",
]
