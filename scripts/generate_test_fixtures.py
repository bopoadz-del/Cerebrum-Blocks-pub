#!/usr/bin/env python3
"""Generate synthetic construction-document fixtures for end-to-end
pipeline plumbing tests.

These fixtures are NOT representative of real project documents. They
verify that the parse → extract → analyse pipeline runs to completion
on inputs of the right shape; they do not validate accuracy on
real-world content.

Outputs (under uploads/_synthetic/):
  - contracts/sample_contract.pdf  — short EPC contract excerpt
  - drawings/sample_drawing.pdf    — annotated plan with dimensions
  - schedules/sample.xer           — minimal Primavera P6 export with
                                     5 activities + 1 critical path
  - photos/sample_site.png         — solid-colour PNG (placeholder)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "uploads" / "_synthetic"
for sub in ("contracts", "drawings", "schedules", "photos"):
    (OUT / sub).mkdir(parents=True, exist_ok=True)


def make_contract_pdf() -> Path:
    """Synthetic EPC contract excerpt with clauses the extractor should
    pick up: contract value, advance payment %, retention %, LD per day,
    and shall-clauses for each party."""
    import fitz  # PyMuPDF

    doc = fitz.open()
    page = doc.new_page()
    text = """\
EPC CONTRACT — SAMPLE

PARTIES
The Employer: Sample Holdings Ltd.
The Contractor: ACME Construction Co.

1. CONTRACT VALUE
The total contract value is USD 5,250,000.00 (Five Million Two Hundred
Fifty Thousand United States Dollars), inclusive of VAT.

2. ADVANCE PAYMENT
The Employer shall pay an advance payment of 20% upon mobilization,
recoverable from interim payment certificates.

3. RETENTION
A retention of 10% shall be deducted from each interim payment
certificate, released 50% on substantial completion and 50% on issue
of the Final Acceptance Certificate.

4. LIQUIDATED DAMAGES
In the event of delay attributable to the Contractor, liquidated damages
of USD 10,000 per day shall apply, capped at 10% of the Contract Value.

5. OBLIGATIONS
The Contractor shall maintain the works in good condition during the
period of this agreement and ensure compliance with all applicable
safety regulations.

The Employer shall pay all undisputed invoices within 30 days of
receipt.

Both parties shall act in good faith.

6. TERMINATION
Either party may terminate this agreement upon material breach with
30 days written notice.

7. FORCE MAJEURE
Neither party shall be liable for delays caused by events of force
majeure including pandemic, war, or natural disaster.

8. DISPUTE RESOLUTION
Disputes shall be resolved through arbitration under ICC rules,
seated in London, UK.
"""
    page.insert_text((50, 50), text, fontsize=10)
    out = OUT / "contracts" / "sample_contract.pdf"
    doc.save(out)
    doc.close()
    return out


def make_drawing_pdf() -> Path:
    """A drawing-shaped PDF with text dimensions and BOQ-like quantity
    markings. Not a real drawing — text-only — but the regex extractor
    treats text the same regardless of source."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    text = """\
ARCHITECTURAL DRAWING A-101 — GROUND FLOOR PLAN
SCALE 1:100  REV A  DATE 2026-01-15

DIMENSIONS
- Building footprint: 30.0 m x 20.0 m
- Total floor area: 600 m2 (gross)
- Net usable area: 540 m²

QUANTITIES (Preliminary BOQ)
- Concrete (C30): 150 m3
- Reinforcement steel: 12,000 kg
- Formwork area: 1,200 m2
- Brick masonry: 800 m2
- Plaster: 1,600 m²
- Floor tiling: 540 m2
- Painting: 2,400 m²

NOTES
NOTE: Verify dimension of column C-3 on detail 5/A-301.
NOTE: TBD — finishing schedule for lobby.
NOTE: Refer to structural drawing S-201 for slab thickness.

CRITICAL DIMENSIONS — TBC at site survey.
"""
    page.insert_text((50, 50), text, fontsize=10)
    out = OUT / "drawings" / "sample_drawing.pdf"
    doc.save(out)
    doc.close()
    return out


def make_xer_file() -> Path:
    """Minimal Primavera P6 XER export. The parser looks for %T headers
    delimiting tables, %F field-name rows, and %R record rows."""
    xer = """\
ERMHDR\t20.12\t2026-01-15\tProject\tSCRIPT\tcb-ai\tdb\tProject Manager\tAdmin\t\tWBS\t\t
%T\tPROJECT
%F\tproj_id\tproj_short_name\tplan_start_date\tplan_end_date
%R\t1\tSampleProject\t2026-02-01 08:00\t2026-12-31 17:00
%T\tCALENDAR
%F\tclndr_id\tclndr_name
%R\t1\tStandard 5-day
%T\tTASK
%F\ttask_id\ttask_code\ttask_name\ttarget_drtn_hr_cnt\ttotal_float_hr_cnt\tfree_float_hr_cnt\tact_work_qty\ttarget_work_qty\ttarget_start_date\ttarget_end_date
%R\t101\tA1000\tMobilization\t40\t0\t0\t0\t40\t2026-02-01 08:00\t2026-02-08 17:00
%R\t102\tA1010\tFoundation excavation\t160\t0\t0\t0\t160\t2026-02-09 08:00\t2026-03-15 17:00
%R\t103\tA1020\tConcrete foundation pour\t80\t0\t0\t0\t80\t2026-03-16 08:00\t2026-03-30 17:00
%R\t104\tA1030\tStructural steel erection\t320\t40\t0\t0\t320\t2026-04-01 08:00\t2026-06-30 17:00
%R\t105\tA1040\tCommissioning\t80\t0\t0\t0\t80\t2026-12-15 08:00\t2026-12-31 17:00
%T\tTASKPRED
%F\ttask_id\tpred_task_id\tpred_type
%R\t102\t101\tPR_FS
%R\t103\t102\tPR_FS
%R\t104\t103\tPR_FS
%R\t105\t104\tPR_FS
%E
"""
    out = OUT / "schedules" / "sample.xer"
    out.write_text(xer)
    return out


def make_photo_png() -> Path:
    """Single-pixel PNG — a placeholder so the photos pipeline doesn't
    error on missing files. Real OCR/CV testing requires real photos."""
    import struct
    import zlib

    # 1x1 grey PNG
    raw = struct.pack(">I", 0) + b"\x80" + b"\x80" + b"\x80"  # one grey pixel
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = (
        struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    )
    ihdr_crc = struct.pack(">I", zlib.crc32(ihdr[4:]))
    raw_chunk_data = b"\x00\x80\x80\x80"
    compressed = zlib.compress(raw_chunk_data)
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed
    idat_crc = struct.pack(">I", zlib.crc32(idat[4:]))
    iend = struct.pack(">I", 0) + b"IEND"
    iend_crc = struct.pack(">I", zlib.crc32(iend[4:]))

    out = OUT / "photos" / "sample_site.png"
    out.write_bytes(sig + ihdr + ihdr_crc + idat + idat_crc + iend + iend_crc)
    return out


def main() -> int:
    paths = []
    try:
        import fitz  # noqa: F401
    except ImportError:
        print("PyMuPDF (fitz) not installed — skipping PDF fixtures.", file=sys.stderr)
        print("Install with: pip install pymupdf", file=sys.stderr)
    else:
        paths.append(make_contract_pdf())
        paths.append(make_drawing_pdf())

    paths.append(make_xer_file())
    paths.append(make_photo_png())

    print("Generated synthetic fixtures:")
    for p in paths:
        print(f"  {p.relative_to(ROOT)}  ({p.stat().st_size} bytes)")
    print()
    print("Run the pipeline against them:")
    print("  ./test_real_files.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
