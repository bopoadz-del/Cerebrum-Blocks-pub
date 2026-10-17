"""Capability-enforcing proxy for block instances (Track B Phase 4).

The proxy wraps a block instance and enforces the permissions declared in its
manifest. It is used both as a runtime decision point (safe to run in-process
vs must run out-of-process) and as a thin guard around in-process execution.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.core.block_capabilities import BlockCapabilities

logger = logging.getLogger(__name__)


class CapabilityProxy:
    """Wrap a block instance with its declared runtime capabilities.

    Attribute access is delegated to the wrapped instance so existing code
    (e.g. ``block.name``, ``block.execute``) keeps working transparently.
    """

    def __init__(self, instance: Any, capabilities: BlockCapabilities) -> None:
        self._instance = instance
        self._capabilities = capabilities

    @property
    def _capabilities_(self) -> BlockCapabilities:
        """Expose the proxy's capability set for dispatchers/tests."""
        return self._capabilities

    @property
    def requires_out_of_process(self) -> bool:
        """Return True when this block must not run in the main process."""
        return self._capabilities.must_run_out_of_process

    def allows_dependency(self, dep_name: str) -> bool:
        """Return True if the block is permitted to access ``dep_name``."""
        return self._capabilities.allows_block_access(dep_name)

    def __getattr__(self, name: str) -> Any:
        """Delegate almost all attribute access to the wrapped instance."""
        if name in ("_instance", "_capabilities"):
            raise AttributeError(name)
        return getattr(self._instance, name)

    async def execute(self, input_data: Any = None, params: Dict = None) -> Dict:
        """Execute the wrapped block, enforcing in-process capability rules."""
        if self.requires_out_of_process:
            raise RuntimeError(
                f"block {self._instance.name!r} requires out-of-process execution "
                f"(capabilities: {self._capabilities})"
            )
        return await self._instance.execute(input_data, params or {})

    async def process(self, input_data: Any = None, params: Dict = None) -> Dict:
        """Process the wrapped block, enforcing in-process capability rules."""
        if self.requires_out_of_process:
            raise RuntimeError(
                f"block {self._instance.name!r} requires out-of-process execution "
                f"(capabilities: {self._capabilities})"
            )
        return await self._instance.process(input_data, params or {})

    def __repr__(self) -> str:
        return f"<CapabilityProxy {self._instance!r} caps={self._capabilities}>"
