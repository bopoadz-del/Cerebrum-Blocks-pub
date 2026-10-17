"""Storage backends a learning_engine is HANDED, never ones it finds.

KERNEL_DEFAULTS 1.5 applied to learning state: the block does not choose
a file path and does not read ``DATA_DIR`` / ``LEARNING_ENGINE_STORAGE``.
The platform (or a test) constructs a backend and puts it on the block's
config as ``storage_backend``.

Two backends ship here so a caller has something to inject. Neither is
imported by the block as a default path — the block's fallback is an
in-process dict it constructs itself, the same shape as CacheManager's
memory rung.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

# Duck-typed contract the block calls: ``load() -> dict`` and
# ``save(state) -> None``. A Protocol with ``...`` bodies is a hollow
# function under scripts/audit_stubs.py, so the contract is this
# comment plus the two real backends below — not an unimplemented
# interface class.


class MemoryLearningStore:
    """In-process dict. Lost on restart. Visible as the fallback rung."""

    def __init__(self, initial: Dict[str, Any] | None = None) -> None:
        self._state: Dict[str, Any] = initial if initial is not None else {
            "formulas": {},
            "history": [],
        }

    def load(self) -> Dict[str, Any]:
        return self._state

    def save(self, state: Dict[str, Any]) -> None:
        self._state = state


class FileLearningStore:
    """A file the *caller* named. The block never picks this path.

    Durability is a property of the path the platform handed over (a
    mounted disk, a tmp dir in a test), not of anything inside the
    block. That is the same guarantee the previous DATA_DIR default
    was trying to make, without the block reaching for the environment.
    """

    def __init__(self, path: str) -> None:
        if not path or not str(path).strip():
            raise ValueError("FileLearningStore requires a path the caller named")
        self.path = str(path)

    def load(self) -> Dict[str, Any]:
        target = Path(self.path)
        if not target.is_file():
            return {"formulas": {}, "history": []}
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"formulas": {}, "history": []}
        if not isinstance(payload, dict):
            return {"formulas": {}, "history": []}
        return payload

    def save(self, state: Dict[str, Any]) -> None:
        target = Path(self.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(state, indent=2), encoding="utf-8")
