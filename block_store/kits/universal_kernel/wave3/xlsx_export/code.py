"""Neutral XLSX workbook builder."""

from __future__ import annotations

import io
import json
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openpyxl import Workbook


class XLSXExportError(ValueError):
    """Raised when an XLSX export cannot be completed."""


@dataclass
class WorkbookBuilder:
    """Builder for neutral XLSX workbooks."""

    _workbook: Workbook = field(default_factory=Workbook, init=False)
    _sheets: Dict[str, Any] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        # Remove the default sheet so callers control sheet names.
        self._workbook.remove(self._workbook.active)

    def add_sheet(self, name: str) -> Any:
        """Create a new worksheet and return it."""
        if name in self._sheets:
            raise XLSXExportError(f"sheet '{name}' already exists")
        worksheet = self._workbook.create_sheet(title=name)
        self._sheets[name] = worksheet
        return worksheet

    def _require_sheet(self, name: str) -> Any:
        worksheet = self._sheets.get(name)
        if worksheet is None:
            raise XLSXExportError(f"sheet '{name}' does not exist")
        return worksheet

    def add_header(self, sheet: str, headers: List[Any]) -> None:
        """Write a header row to the sheet."""
        worksheet = self._require_sheet(sheet)
        for column, value in enumerate(headers, start=1):
            worksheet.cell(row=1, column=column, value=self._coerce(value))

    def add_row(self, sheet: str, row: List[Any]) -> None:
        """Append a data row to the sheet."""
        worksheet = self._require_sheet(sheet)
        worksheet.append([self._coerce(value) for value in row])

    def _coerce(self, value: Any) -> Any:
        """Convert invalid cell types to strings; fail-closed but explicit."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (list, dict)):
            warnings.warn("complex cell value converted to JSON string", stacklevel=3)
            return json.dumps(value, sort_keys=True)
        warnings.warn("non-primitive cell value converted to string", stacklevel=3)
        return str(value)

    def to_bytes(self) -> bytes:
        """Serialize the workbook to bytes."""
        buf = io.BytesIO()
        self._workbook.save(buf)
        return buf.getvalue()


def export_table(
    headers: Optional[List[Any]] = None,
    rows: Optional[List[List[Any]]] = None,
    title: str = "export",
) -> bytes:
    """Convenience export of headers and rows to a single-sheet workbook."""
    headers = headers or []
    rows = rows or []
    builder = WorkbookBuilder()
    builder.add_sheet(title)
    if headers:
        builder.add_header(title, headers)
    for row in rows:
        builder.add_row(title, row)
    return builder.to_bytes()
