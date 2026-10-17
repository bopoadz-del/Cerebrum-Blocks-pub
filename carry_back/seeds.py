"""Seeded Carry-Back acceptance fixtures, written at run time (never committed).

The two seeded fixtures (a block-level fix that must migrate, a platform-specific
fix that must be declined) are synthetic. They are generated into a directory
on demand -- by the tests, by ``python -m carry_back self-test`` when no
``fixtures/carry_back/`` exists, and by the workflow before it proposes -- so the
repository carries no fixture capture tree.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

SEEDS: dict[str, dict[str, str]] = {'block_level_fix': {'diff.patch': 'diff --git a/app/blocks/pdf.py b/app/blocks/pdf.py\r\n'
                                   'index 1111111..2222222 100644\r\n'
                                   '--- a/app/blocks/pdf.py\r\n'
                                   '+++ b/app/blocks/pdf.py\r\n'
                                   '@@ -90,6 +90,12 @@ def _try_ocr_fallback(\r\n'
                                   '         return None\r\n'
                                   '     finally:\r\n'
                                   '         doc.close()\r\n'
                                   '+\r\n'
                                   '+\r\n'
                                   '+def _guard_empty_path(pdf_path: str) -> None:\r\n'
                                   '+    """Pin: empty/None path must raise before fitz.open '
                                   '(carry-back seeded fix)."""\r\n'
                                   '+    if not pdf_path or not str(pdf_path).strip():\r\n'
                                   '+        raise ValueError("pdf_path must be a non-empty '
                                   'path")\r\n'
                                   ' \r\n'
                                   ' \r\n'
                                   ' class PDFBlock(TypedBlock):\r\n',
                     'meta.yaml': '# Seeded acceptance fixture: block-level fix from a product.\r\n'
                                  'source_product: The_Fork\r\n'
                                  'bug_class: pdf-empty-path-npe\r\n'
                                  'source_ref: fixtures/carry_back/block_level_fix (seeded)\r\n'
                                  'expected_classification: block_level\r\n'
                                  'block: pdf\r\n',
                     'paths.txt': 'app/blocks/pdf.py\r\n'},
 'platform_specific_fix': {'diff.patch': 'diff --git a/render.yaml b/render.yaml\r\n'
                                         'index 1111111..2222222 100644\r\n'
                                         '--- a/render.yaml\r\n'
                                         '+++ b/render.yaml\r\n'
                                         '@@ -10,6 +10,7 @@ services:\r\n'
                                         '     healthCheckPath: /health\r\n'
                                         '+    # product-only: bind health to Fork deploy '
                                         'layout\r\n'
                                         '     envVars:\r\n'
                                         '       - key: ENV\r\n'
                                         '         value: production\r\n'
                                         'diff --git a/frontend/src/App.tsx '
                                         'b/frontend/src/App.tsx\r\n'
                                         'index 1111111..2222222 100644\r\n'
                                         '--- a/frontend/src/App.tsx\r\n'
                                         '+++ b/frontend/src/App.tsx\r\n'
                                         '@@ -1,3 +1,4 @@\r\n'
                                         '+// product UI-only tweak — not a store block\r\n'
                                         ' export function App() {\r\n'
                                         '   return <div>Fork</div>;\r\n'
                                         ' }\r\n'
                                         'diff --git a/app/routers/health.py '
                                         'b/app/routers/health.py\r\n'
                                         'index 1111111..2222222 100644\r\n'
                                         '--- a/app/routers/health.py\r\n'
                                         '+++ b/app/routers/health.py\r\n'
                                         '@@ -1,3 +1,4 @@\r\n'
                                         '+# product router glue — not in store block identity '
                                         'paths\r\n'
                                         ' from fastapi import APIRouter\r\n'
                                         ' router = APIRouter()\r\n',
                           'meta.yaml': '# Seeded acceptance fixture: platform-specific fix (must '
                                        'decline).\r\n'
                                        'source_product: The_Fork\r\n'
                                        'bug_class: render-healthcheck-path\r\n'
                                        'source_ref: fixtures/carry_back/platform_specific_fix '
                                        '(seeded)\r\n'
                                        'expected_classification: platform_specific\r\n',
                           'paths.txt': 'render.yaml\r\n'
                                        'frontend/src/App.tsx\r\n'
                                        'app/routers/health.py\r\n'
                                        '.env.example\r\n'}}

_CACHE: Path | None = None


def write_seeds(dest: Path) -> Path:
    """Write every seeded fixture under ``dest`` (``dest/<fixture>/<file>``); return ``dest``."""
    dest = Path(dest)
    for fixture, files in SEEDS.items():
        d = dest / fixture
        d.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (d / name).write_bytes(text.encode("utf-8"))
    return dest


def seed_dir() -> Path:
    """A per-process temporary directory holding the seeded fixtures."""
    global _CACHE
    if _CACHE is None or not _CACHE.is_dir():
        _CACHE = write_seeds(Path(tempfile.mkdtemp(prefix="carry_back_seeds_")))
    return _CACHE


if __name__ == "__main__":
    import sys

    out = write_seeds(Path(sys.argv[1] if len(sys.argv) > 1 else "fixtures/carry_back"))
    print(f"seeded {len(SEEDS)} fixture(s) under {out}")
