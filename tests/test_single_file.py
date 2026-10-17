#!/usr/bin/env python3
"""Pipeline smoke test for a single construction document.

Usage:
    python3 tests/test_single_file.py <path>

The file extension drives which container action runs:
  .pdf .docx .txt .md           → auto_pipeline
  .xer .xml                     → parse_primavera_schedule
  .dxf .dwg                     → drawing_qto block
  .ifc                          → bim_extract
  .jpg .jpeg .png .webp .bmp    → qa_qc_inspection
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Match the test environment so cb_dev_key loads (consistent with conftest).
os.environ.setdefault("ENV", "test")


def _read_pdf_text(path: Path) -> str:
    import fitz
    doc = fitz.open(str(path))
    out: list[str] = []
    for page in doc:
        out.append(page.get_text())
    doc.close()
    return "\n".join(out)


def _read_docx_text(path: Path) -> str:
    try:
        import docx
    except ImportError:
        return ""
    d = docx.Document(str(path))
    return "\n".join(p.text for p in d.paragraphs)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _summarise_panels(result: dict) -> None:
    panels = result.get("panels") or []
    if not panels:
        print("  panels: (none)")
        return
    print(f"  panels: {len(panels)}")
    for p in panels:
        ptype = p.get("type", "?")
        title = p.get("title", "")
        data = p.get("data", {})
        if isinstance(data, list):
            print(f"   - {ptype:20} {title}  ({len(data)} items)")
        elif isinstance(data, dict):
            keys = list(data.keys())[:5]
            print(f"   - {ptype:20} {title}  keys={keys}")
        else:
            print(f"   - {ptype:20} {title}")
    warnings = result.get("pipeline_warnings") or []
    if warnings:
        print(f"  pipeline_warnings: {len(warnings)}")
        for w in warnings[:5]:
            print(f"   - {w.get('panel')}: {w.get('error', '')[:80]}")


async def _run_pdf_or_text(path: Path, container) -> None:
    if path.suffix.lower() == ".pdf":
        text = _read_pdf_text(path)
    elif path.suffix.lower() == ".docx":
        text = _read_docx_text(path)
    else:
        text = _read_text(path)
    print(f"  extracted: {len(text)} chars")
    if not text.strip():
        print("  (empty extraction — likely scanned PDF; OCR not invoked here)")
        return
    res = await container.auto_pipeline(
        {"file_path": str(path), "extracted_text": text[:100_000]},
        {"doc_type": "auto"},
    )
    print(f"  status: {res.get('status')}  doc_type: {res.get('doc_type')}")
    _summarise_panels(res)


async def _run_schedule(path: Path, container) -> None:
    res = await container.parse_primavera_schedule(
        {"file_path": str(path)},
        {"include_details": True},
    )
    print(f"  status: {res.get('status')}")
    summary = res.get("summary") or {}
    if summary:
        print(f"  total_activities: {summary.get('total_activities')}")
        print(f"  critical_activities: {summary.get('critical_activities')}")
        print(f"  project_duration_days: {summary.get('project_duration')}")
    activities = res.get("detailed_activities") or []
    if activities:
        print("  first 3 activities:")
        for a in activities[:3]:
            name = a.get("task_name") or a.get("name") or a.get("task") or "?"
            print(f"   - {name}")


async def _run_drawing_qto(path: Path) -> None:
    from app.blocks.drawing_qto import DrawingQTOBlock
    block = DrawingQTOBlock()
    res = await block.process({"file_path": str(path)}, {})
    print(f"  status: {res.get('status')}")
    print(f"  total_area_m2: {res.get('total_area_m2')}")
    print(f"  total_length_m: {res.get('total_length_m')}")
    print(f"  layers: {(res.get('layers') or [])[:5]}")


async def _run_bim(path: Path, container) -> None:
    res = await container.bim_extract(
        {"file_path": str(path)},
        {},
    ) if hasattr(container, "bim_extract") else {"status": "skipped",
                                                  "reason": "bim_extract action not on container"}
    print(f"  status: {res.get('status')}")
    if res.get("elements"):
        print(f"  elements: {len(res['elements'])}")


async def _run_photo(path: Path, container) -> None:
    res = await container.qa_qc_inspection({"file_path": str(path)}, {})
    print(f"  status: {res.get('status')}")
    if res.get("error"):
        print(f"  error: {res['error']}")
    if res.get("findings"):
        print(f"  findings: {len(res['findings'])}")


async def main(path_str: str) -> int:
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        return 1
    print(f"\n{'=' * 60}\nFile: {path}\n{'=' * 60}")
    print(f"  size: {path.stat().st_size:,} bytes")

    from app.containers.construction import ConstructionContainer
    container = ConstructionContainer()

    ext = path.suffix.lower()
    try:
        if ext in (".pdf", ".docx", ".txt", ".md"):
            await _run_pdf_or_text(path, container)
        elif ext in (".xer", ".xml"):
            await _run_schedule(path, container)
        elif ext in (".dxf", ".dwg"):
            await _run_drawing_qto(path)
        elif ext == ".ifc":
            await _run_bim(path, container)
        elif ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
            await _run_photo(path, container)
        else:
            print(f"  ERROR: unsupported extension {ext}")
            return 2
    except Exception as exc:
        print(f"  ERROR: {type(exc).__name__}: {exc}")
        return 3
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    sys.exit(asyncio.run(main(sys.argv[1])))
