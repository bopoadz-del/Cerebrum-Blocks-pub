"""Force UTF-8 on stdout/stderr so non-ASCII output doesn't crash on Windows.

On Windows with cp1252 (or any non-UTF-8 encoding), box-drawing characters
and document content can raise ``UnicodeEncodeError``. Reconfigure the
standard streams to use UTF-8 with ``errors="replace"``. The call is
idempotent and safe on systems already using UTF-8.
"""

from __future__ import annotations

import sys


def _reconfigure_stream(name: str) -> None:
    stream = getattr(sys, name, None)
    if stream is None:
        return
    # ``reconfigure`` exists on TextIOWrapper (the usual stdout/stderr).
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")


def ensure_utf8_output() -> None:
    """Reconfigure stdout and stderr to UTF-8 with replacement errors."""
    _reconfigure_stream("stdout")
    _reconfigure_stream("stderr")
