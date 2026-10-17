"""The base class that makes a block's failures visible, and the free
function that does the same for a block that has not adopted it yet.

ADDITIVE BY CONSTRUCTION
------------------------
``UniversalBlock`` is not touched, and neither is any block in
``app/blocks/``. ``execute()`` keeps its envelope and its ``success``/
``error`` vocabulary, so every existing caller and every existing test sees
exactly what it saw before.

Two ways in, and the second is the important one:

``ContractBlock``
    A new block subclasses this instead of ``UniversalBlock`` and returns a
    :class:`~app.core.block_result.BlockResult` from ``process``. It gets the
    exception guard for free.

:func:`safe_call`
    Runs **any** ``UniversalBlock`` -- adopted or not, written years ago --
    and returns a ``BlockResult``. Nothing about the block changes. This is
    what the store-wide conformance harness uses to get a status out of 129
    blocks that have never heard of this module.

WHY THE GUARD RE-RAISES ONLY ON A FLAG
--------------------------------------
Catching every exception and reporting ``failed`` is right in production: a
raised exception that escapes a block takes down whatever was orchestrating
it, and the reader learns nothing about which block failed or why.

It is wrong in a debugger. So ``reraise_exceptions`` exists, defaults to
``False``, and when set lets the exception through untouched -- after the
result has been built, so the two paths cannot disagree about what happened.

The flag is read from the block's config, not from ``os.environ``: block code
does not reach into the environment (see the Config injection work in L2.5).
"""

from __future__ import annotations

import inspect
import traceback
from typing import Any, Dict, Optional

from app.core.block_result import BlockResult, to_block_result
from app.core.universal_base import UniversalBlock

#: How much of a traceback goes into ``evidence``. Enough to locate the
#: failure, not so much that a log becomes unreadable.
_TRACEBACK_CHARS = 4000


def _flag(block: Any, name: str, default: bool = False) -> bool:
    """Read a boolean flag from the block's config, then its class."""
    config = getattr(block, "config", None)
    if isinstance(config, dict) and name in config:
        return bool(config[name])
    return bool(getattr(type(block), name, default))


def _failure_from_exception(block: Any, exc: BaseException) -> BlockResult:
    name = getattr(block, "name", None) or type(block).__name__
    return BlockResult.failed(
        "%s raised %s: %s" % (name, type(exc).__name__, exc),
        evidence=[
            {
                "kind": "traceback",
                "block": name,
                "error_type": type(exc).__name__,
                "traceback": "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )[-_TRACEBACK_CHARS:],
            }
        ],
    )


async def safe_call(
    block: UniversalBlock,
    input_data: Any = None,
    params: Optional[Dict] = None,
    *,
    reraise: Optional[bool] = None,
) -> BlockResult:
    """Invoke ``block.process`` and return a ``BlockResult``, always.

    Handles the three things that make a raw ``process()`` call unsafe to run
    across a whole store:

    * ``process`` may be ``async def`` or a plain ``def``. Both are accepted.
    * ``process`` may raise. The exception becomes ``failed`` with the type,
      the message and the traceback in ``evidence``.
    * ``process`` may return ``None``, a dict, or something else entirely.
      :func:`~app.core.block_result.to_block_result` normalises all of it.

    Args:
        reraise: Overrides the block's ``reraise_exceptions`` flag. ``None``
            (the default) means "use the block's own setting".
    """
    should_reraise = _flag(block, "reraise_exceptions") if reraise is None else reraise
    try:
        raw = block.process(input_data, params or {})
        if inspect.isawaitable(raw):
            raw = await raw
    except Exception as exc:  # noqa: BLE001 -- the whole point of the guard
        result = _failure_from_exception(block, exc)
        if should_reraise:
            raise
        return result
    return to_block_result(raw)


class ContractBlock(UniversalBlock):
    """A block that reports outcomes instead of returning bare dicts.

    Subclasses implement ``process`` and should return a ``BlockResult``.
    Returning a legacy dict is still accepted -- :func:`safe_call` adapts it
    -- so a block can be migrated in one step or two.

    ``execute()`` is inherited unchanged. A ``ContractBlock`` dropped into an
    existing pipeline behaves exactly like any other block; the contract is
    available to callers that ask for it via :meth:`run`.
    """

    #: Let an exception escape ``run``/``safe_call`` instead of becoming a
    #: ``failed`` result. Off in production; on when you are debugging.
    reraise_exceptions: bool = False

    async def run(
        self, input_data: Any = None, params: Optional[Dict] = None
    ) -> BlockResult:
        """Run this block under the guard. Never returns ``None``."""
        return await safe_call(self, input_data, params)
