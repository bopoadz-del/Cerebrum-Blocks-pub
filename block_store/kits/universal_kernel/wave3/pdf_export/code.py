"""Neutral PDF builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


class PDFConfigurationError(Exception):
    """Raised when PDF rendering is misconfigured or dependencies are missing."""


class PDFExportError(ValueError):
    """Raised when a PDF export cannot be completed."""


@dataclass
class PDFBuilder:
    """Builder for neutral PDF documents."""

    title: str = "Document"
    author: str = ""
    _elements: List[Dict[str, Any]] = field(default_factory=list, init=False)

    def add_heading(self, text: str) -> "PDFBuilder":
        """Add a heading element."""
        self._elements.append({"type": "heading", "text": str(text)})
        return self

    def add_paragraph(self, text: str) -> "PDFBuilder":
        """Add a paragraph element."""
        self._elements.append({"type": "paragraph", "text": str(text)})
        return self

    def add_table(self, headers: List[str], rows: List[List[Any]]) -> "PDFBuilder":
        """Add a table element."""
        self._elements.append(
            {
                "type": "table",
                "headers": list(headers),
                "rows": [list(row) for row in rows],
            }
        )
        return self

    def to_bytes(self) -> bytes:
        """Render the document to PDF bytes.

        Falls back to a plain-text representation labelled with
        ``honesty="fallback_text_pdf"`` when fpdf2 is unavailable.
        """
        try:
            from fpdf import FPDF
            from fpdf.enums import XPos, YPos
        except ImportError:
            return self._fallback_text_pdf()

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_title(self.title)
        if self.author:
            pdf.set_author(self.author)

        # Use a core font to avoid missing-font configuration errors.
        pdf.set_font("Helvetica", size=12)

        next_line = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}

        if self.title:
            pdf.set_font_size(16)
            pdf.cell(0, 10, self.title, **next_line)
            pdf.ln(4)
            pdf.set_font_size(12)

        for element in self._elements:
            kind = element["type"]
            if kind == "heading":
                pdf.set_font_size(14)
                pdf.cell(0, 10, str(element["text"]), **next_line)
                pdf.set_font_size(12)
                pdf.ln(2)
            elif kind == "paragraph":
                pdf.multi_cell(0, 8, str(element["text"]))
                pdf.ln(2)
            elif kind == "table":
                self._render_table(pdf, element, next_line)

        return pdf.output()

    def _render_table(
        self,
        pdf: Any,
        element: Dict[str, Any],
        next_line: Dict[str, Any],
    ) -> None:
        headers = element["headers"]
        rows = element["rows"]
        col_width = 40
        if headers:
            pdf.set_font("Helvetica", "B", 12)
            for header in headers:
                pdf.cell(col_width, 10, str(header), border=1)
            pdf.ln()
            pdf.set_font("Helvetica", "", 12)
        for row in rows:
            for cell in row:
                pdf.cell(col_width, 10, str(cell), border=1)
            pdf.ln()
        pdf.ln(2)

    def _fallback_text_pdf(self) -> bytes:
        """Plain-text fallback when fpdf2 is not installed."""
        lines = [self.title]
        if self.author:
            lines.append(f"Author: {self.author}")
        lines.append("")
        for element in self._elements:
            kind = element["type"]
            if kind == "heading":
                lines.append(f"## {element['text']}")
            elif kind == "paragraph":
                lines.append(element["text"])
            elif kind == "table":
                if element["headers"]:
                    lines.append(" | ".join(str(h) for h in element["headers"]))
                for row in element["rows"]:
                    lines.append(" | ".join(str(cell) for cell in row))
            lines.append("")
        text = "\n".join(lines) + f"\n\nhonesty=fallback_text_pdf\n"
        return text.encode("utf-8")
