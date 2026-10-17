"""Generate the two synthetic drawing fixtures the drawing tests read.

Both sheets are invented: no real title block, firm, client, project or
place. They carry what a real construction sheet carries, so the PDF, OCR and
drawing-reader tests exercise real extraction: a title block in the bottom
band with labelled fields, a full drawing number, general notes, match-line
callouts, CAD tag soup and red markup.

    python tests/fixtures/make_synthetic_drawings.py

writes ``synthetic_tm_detail.pdf`` and ``synthetic_tm_keyplan.pdf`` next to
this file. The output is deterministic (fixed seed, fixed creation date).
"""
from __future__ import annotations

import random
from pathlib import Path

from reportlab.lib.colors import Color, black, red
from reportlab.lib.pagesizes import A1, landscape
from reportlab.pdfgen import canvas

HERE = Path(__file__).parent
W, H = landscape(A1)

DETAIL_NUMBER = "PK-INF-001-0000-FRM-DWG-TM-200-1100010-A"
KEYPLAN_NUMBER = "PK-INF-001-0000-FRM-DWG-TM-200-0015001"

NOTES = [
    "GENERAL NOTES:",
    "1. ALL DIMENSIONS ARE IN METERS UNLESS OTHERWISE NOTED.",
    "2. COORDINATES ARE IN WGS-84 / UTM ZONE 37N; LEVELS ARE TO THE PROJECT DATUM.",
    "3. TEMPORARY TRAFFIC SIGNS SHALL BE INSTALLED BEFORE ANY WORK STARTS ON THE CARRIAGEWAY.",
    "4. ALL BARRIERS SHALL BE INSPECTED DAILY AND REINSTATED WHERE DISPLACED.",
    "5. PEDESTRIAN ROUTES SHALL BE KEPT OPEN AND SEPARATED FROM THE WORKS AT ALL TIMES.",
    "6. THE CONTRACTOR SHALL SUBMIT A TRAFFIC MANAGEMENT METHOD STATEMENT FOR APPROVAL.",
    "7. FOR THE OVERALL ARRANGEMENT REFER TO KEY PLAN " + KEYPLAN_NUMBER + ".",
]


def _title_block(c: canvas.Canvas, number: str, title: str, sheet: str) -> None:
    x0, y0, w, h = W - 900, 20, 880, 230
    c.setStrokeColor(black)
    c.rect(x0, y0, w, h)
    c.setFont("Helvetica", 9)
    fields = [
        "PROJECT: SAMPLE ROAD UPGRADE",
        "CLIENT: EXAMPLE DEVELOPMENT AUTHORITY",
        "LOCATION: SAMPLE REGION",
        "CONSULTANT: Sample Design Consultant",
        "DRAWN BY: DRAFTER A",
        "CHECKED BY: CHECKER B",
        "SCALE: 1:500",
        f"SHEET: {sheet}",
        "INFRASTRUCTURE DESIGN PACKAGE",
    ]
    for i, line in enumerate(fields):
        c.drawString(x0 + 12, y0 + h - 18 - i * 14, line)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(x0 + 330, y0 + 120, title)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(x0 + 330, y0 + 40, number)


def _notes(c: canvas.Canvas) -> None:
    c.setFont("Helvetica", 10)
    for i, line in enumerate(NOTES):
        c.drawString(W - 900, H - 60 - i * 16, line)


def _cad_tags(c: canvas.Canvas, rng: random.Random, count: int) -> None:
    c.setFont("Helvetica", 5)
    callout_rows = (H - 120, 330, 900, 700, 1100, 1300, 500)
    drawn = 0
    while drawn < count:
        tag = f"DE{rng.randint(1, 99)}-TM-{rng.randint(1, 999):03d}"
        y = rng.uniform(300, H - 80)
        if any(abs(y - row) < 14 for row in callout_rows):
            continue  # a tag sits on its own line, never on a callout's
        c.drawString(rng.uniform(60, W - 1000), y, tag)
        drawn += 1


def _plan_lines(c: canvas.Canvas, rng: random.Random) -> None:
    c.setStrokeColor(Color(0.3, 0.3, 0.3))
    for _ in range(120):
        c.line(rng.uniform(40, W - 960), rng.uniform(280, H - 40), rng.uniform(40, W - 960), rng.uniform(280, H - 40))


def _callouts(c: canvas.Canvas) -> None:
    c.setFont("Helvetica-Bold", 11)
    c.drawString(80, H - 120, "MATCH LINE : FOR REFERENCE REFER TO SHEET NO : 10")
    c.drawString(80, 330, "MATCH LINE : FOR REFERENCE REFER TO SHEET NO : 12")
    c.setFont("Helvetica", 10)
    c.drawString(600, 900, "PROJECT BOUNDARY")
    c.drawString(900, 700, "BUS STOP")
    c.drawString(1100, 1100, "PROPOSED CARRIAGEWAY")
    c.drawString(400, 1300, "EXISTING FOOTPATH TO BE RETAINED")
    c.drawString(1300, 500, "TEMPORARY CONCRETE BARRIER")


LEGEND = [
    "LEGEND:",
    "EXISTING KERB LINE", "PROPOSED KERB LINE", "TEMPORARY CONCRETE BARRIER (TCB)", "WATER-FILLED BARRIER",
    "TRAFFIC CONE AT 5 M CENTRES", "ADVANCE WARNING SIGN", "DIVERSION ROUTE ARROW", "PEDESTRIAN CROSSING POINT",
    "FLAGMAN POSITION", "WORK ZONE LIMIT", "SAFETY BUFFER ZONE 10 M", "STREET LIGHT TO BE PROTECTED",
    "EXISTING SERVICE CORRIDOR", "TEMPORARY ACCESS FOR EMERGENCY VEHICLES",
]


def _legend(c: canvas.Canvas) -> None:
    c.setFont("Helvetica", 9)
    for i, line in enumerate(LEGEND):
        c.drawString(W - 900, H - 220 - i * 14, line)


def _redlines(c: canvas.Canvas) -> None:
    c.setStrokeColor(red)
    c.setFillColor(Color(1, 0, 0, alpha=0.35))
    c.setLineWidth(6)
    for x, y, w, h in ((700, 850, 260, 120), (1050, 650, 200, 100)):
        c.rect(x, y, w, h, stroke=1, fill=1)
    c.setFillColor(black)


def _sheet(path: Path, number: str, title: str, sheet: str, tags: int, seed: int) -> None:
    rng = random.Random(seed)
    c = canvas.Canvas(str(path), pagesize=(W, H), invariant=1)
    c.setTitle("Synthetic drawing fixture")
    c.setAuthor("")
    c.setCreator("make_synthetic_drawings.py")
    _plan_lines(c, rng)
    _cad_tags(c, rng, tags)
    _callouts(c)
    _notes(c)
    _legend(c)
    _redlines(c)
    _title_block(c, number, title, sheet)
    c.showPage()
    c.save()


def main() -> None:
    _sheet(HERE / "synthetic_tm_detail.pdf", DETAIL_NUMBER, "TRAFFIC MANAGEMENT DETAIL", "11 OF 20", 90, 11)
    _sheet(HERE / "synthetic_tm_keyplan.pdf", KEYPLAN_NUMBER, "TRAFFIC MANAGEMENT KEY PLAN", "1 OF 20", 180, 1)


if __name__ == "__main__":
    main()
