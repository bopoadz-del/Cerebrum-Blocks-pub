"""{{name}} — domain container stub.

Subclasses ``DomainContainer`` (``app/containers/base.py``). When this kit is
published, ``container.py`` is copied to ``app/containers/{{domain}}.py`` per
manifest ``skeleton_artifacts`` / ``artifacts``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict

from app.containers.base import DomainContainer


class {{Domain}}Container(DomainContainer):
    name = "{{domain}}"
    description = "{{description}}"
    version = "0.0.0-skeleton"
    system_prompt_file = "{{domain}}_expert.txt"

    def __init__(self, kit_root: Path | None = None) -> None:
        self.kit_root = kit_root or Path(__file__).resolve().parent

    def get_actions(self) -> Dict[str, Callable]:
        # TODO: wire domain actions (e.g. analyze, summarize, route_to_block)
        return {}
