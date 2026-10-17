"""Medical & Healthcare Suite — domain container stub.

Subclasses ``DomainContainer`` (``app/containers/base.py``). When this kit is
published, ``container.py`` is copied to ``app/containers/medical.py`` per
manifest ``skeleton_artifacts`` / ``artifacts``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict

from app.containers.base import DomainContainer


class MedicalContainer(DomainContainer):
    name = "medical"
    description = "Clinical workflows, patient records intelligence, and healthcare compliance blocks."
    version = "0.0.0-skeleton"
    system_prompt_file = "medical_expert.txt"

    def __init__(self, kit_root: Path | None = None) -> None:
        self.kit_root = kit_root or Path(__file__).resolve().parent

    def get_actions(self) -> Dict[str, Callable]:
        return {
            "ehr_fetch": self._ehr_fetch,
            "health": self._health,
        }

    async def _health(self, input_data: Any, params: Dict) -> Dict:
        return {"status": "healthy", "container": self.name, "version": self.version}

    async def _ehr_fetch(self, input_data: Any, params: Dict) -> Dict:
        """Route to platform medical_ehr_connector."""
        block = self._resolve_block("medical_ehr_connector")
        if block is None:
            return {"status": "error", "error": "medical_ehr_connector block unavailable"}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**data, **(params or {})}
        merged.setdefault("action", "fetch")
        return await block.process(merged, {"action": merged["action"], "resource": merged.get("resource", "Patient")})
