"""Domain container host — kit entry point for Cerebrum Block Store installs.

Kit authors subclass ``DomainContainer`` in ``block_store/kits/{domain}/container.py``.
On publish/install, that file is copied to ``app/containers/{domain}.py`` (see manifest
``skeleton_artifacts`` / ``artifacts``). Subclasses must implement ``get_actions()``
and may override ``get_rag_filters()`` for domain-scoped retrieval.

Example skeleton (``block_store/kits/medical/container.py``)::

    class MedicalContainer(DomainContainer):
        name = "medical"
        system_prompt_file = "medical_expert.txt"

        def __init__(self, kit_root: Path | None = None) -> None:
            self.kit_root = kit_root or Path(__file__).resolve().parent

        def get_actions(self) -> Dict[str, Callable]:
            return {}
"""

from __future__ import annotations

from abc import abstractmethod
from pathlib import Path
from typing import Any, Callable, Dict

from app.core.universal_base import UniversalContainer


class DomainContainer(UniversalContainer):
    """Base class for store-published domain kits.

    Attributes:
        name: Short kit identifier (matches manifest ``id``).
        description: Human-readable summary for discovery UIs.
        version: Semver or skeleton tag (e.g. ``0.0.0-skeleton``).
        system_prompt_file: Filename under ``prompts/`` injected into ``chat()``
            when the caller does not supply ``system_prompt`` / ``system_prompt_file``.
        knowledge_class: Optional knowledge module class for RAG enrichment.
        kit_root: Root of the kit tree (``block_store/kits/{domain}`` during dev,
            or install target once prompts are copied under ``app/``).
    """

    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    system_prompt_file: str = ""
    knowledge_class: type | None = None
    kit_root: Path | None = None

    def resolve_prompt(self, filename: str | None = None) -> str:
        """Load prompt text from kit ``prompts/``, legacy ``app/prompts/``, or app root."""
        fname = filename or self.system_prompt_file
        if not fname:
            return ""
        candidates: list[Path] = []
        if self.kit_root:
            candidates.append(self.kit_root / "prompts" / fname)
            candidates.append(self.kit_root / "app" / "prompts" / fname)
        app_root = Path(__file__).resolve().parents[1]
        candidates.append(app_root / "prompts" / fname)
        for path in candidates:
            if path.is_file():
                return path.read_text(encoding="utf-8")
        return ""

    def get_rag_filters(self) -> Dict[str, Any] | None:
        """Optional domain filters passed to vector/RAG blocks. Override in subclasses."""
        return None

    def _resolve_block(self, name: str):
        from app.blocks import BLOCK_REGISTRY

        if BLOCK_REGISTRY.get(name) is None:
            return None
        from app.dependencies import get_block_instance

        return get_block_instance(name)

    async def chat(self, input_data: Any, params: Dict | None = None) -> Dict:
        """Route to the platform ``chat`` block with domain prompt injection.

        Mirrors the ConstructionContainer pattern: if the caller did not supply
        ``system_prompt`` or ``system_prompt_file``, inject ``self.system_prompt_file``.
        """
        chat_block = self._resolve_block("chat")
        if chat_block is None:
            return {"status": "error", "error": "chat block unavailable"}

        merged = dict(params or {})
        data = input_data if isinstance(input_data, dict) else {}
        if "use_rag" not in merged and not (
            isinstance(input_data, dict) and "use_rag" in input_data
        ):
            merged["use_rag"] = True
        caller_supplied_prompt = (
            merged.get("system_prompt")
            or merged.get("system_prompt_file")
            or data.get("system_prompt")
            or data.get("system_prompt_file")
        )
        if not caller_supplied_prompt and self.system_prompt_file:
            merged["system_prompt_file"] = self.system_prompt_file

        return await chat_block.process(input_data, merged)

    @abstractmethod
    def get_actions(self) -> Dict[str, Callable]:
        """Return action name → async handler for ``route()``."""
        ...

    async def route(self, action: str, input_data: Any, params: Dict) -> Dict:
        handler = self.get_actions().get(action)
        if handler is None:
            return {"status": "error", "error": f"Action '{action}' not implemented"}
        return await handler(input_data, params)
