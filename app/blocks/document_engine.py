"""Compatibility shim for the document_engine platform wrapper.

The ``document_engine/`` package shadows this file for
``import app.blocks.document_engine``. The wrapper body lives in
``document_engine_block.py`` so factory CLONER / runtime-slice scanners
that resolve ``app.blocks.(\\w+)`` find an on-disk module.

Loaders that still open this path by filename get the same class.
"""

from app.blocks.document_engine_block import DocumentEngineBlock

__all__ = ["DocumentEngineBlock"]
