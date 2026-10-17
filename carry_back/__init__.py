"""Carry-Back Agent — store-side proposal-only maintenance (Pillar C).

PROPOSES migrations into the store; never silently mutates main.
LIVE mode is gated until one real migrate + one correct decline are recorded.
"""

from __future__ import annotations

__all__ = ["__version__", "LIVE_ENABLED"]

__version__ = "0.1.0"

# LIVE stays False until acceptance: one migrate + one decline demonstrated.
LIVE_ENABLED = False
