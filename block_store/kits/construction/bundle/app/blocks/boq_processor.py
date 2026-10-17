"""BOQ Processor Block - Parse Excel/CSV/PDF Bills of Quantities into structured line items"""

import logging
import os
from typing import Any, Dict, List, Tuple
from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

logger = logging.getLogger(__name__)


class BOQProcessorBlock(UniversalBlock):
    name = "boq_processor"
    version = "1.0.0"
    description = "Parse Excel/CSV Bills of Quantities into structured quantities and cost breakdown"
    layer = 3
    tags = ["domain", "construction", "boq", "quantities", "excel"]
    requires = []

    default_config = {
        "currency": "USD",
        "include_zero_qty": False,
    }

    ui_schema = {
        "input": {
            "type": "file",
            "accept": [".xlsx", ".xls", ".csv", ".pdf"],
            "placeholder": "Upload BOQ spreadsheet (.xlsx, .csv) or BOQ PDF...",
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "item_count", "type": "number", "label": "Line Items"},
                {"name": "total_cost", "type": "number", "unit": "USD", "label": "Total Cost"},
                {"name": "line_items", "type": "list", "label": "Line Items"},
                {"name": "cost_breakdown", "type": "json", "label": "Cost Breakdown"},
            ],
        },
        "quick_actions": [
            {"icon": "📊", "label": "Parse BOQ", "prompt": "Parse and summarize this Bill of Quantities"},
            {"icon": "💰", "label": "Cost Summary", "prompt": "Give me a cost breakdown by trade/division"},
        ],
    }

    # Common BOQ column name aliases
    _COL_MAP = {
        "description": ["description", "item_description", "work_item", "item", "activity", "desc", "name"],
        "quantity": ["quantity", "qty", "amount", "no", "number", "count"],
        "unit": ["unit", "uom", "u/m", "unit_of_measure", "measure"],
        "rate": ["rate", "unit_cost", "unit_price", "price", "unit_rate", "cost_per_unit", "cost/unit"],
        "total": ["total", "total_cost", "amount", "line_total", "extended_price", "cost", "value"],
        "section": ["section", "division", "trade", "category", "csi_div", "package", "work_package"],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        if params.get("action") in ("status", "health"):
            return {"status": "success", "ready": True}
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}

        file_path = data.get("file_path") or params.get("file_path") or data.get("text") or data.get("input") or (input_data if isinstance(input_data, str) else "")
        if not file_path or not os.path.exists(str(file_path)):
            return {
                "status": "error",
                "error": "No valid BOQ file provided. Upload .xlsx, .xls, or .csv",
            }

        ext = os.path.splitext(file_path)[1].lower()
        try:
            # Decrypt-to-temp when the stored file is encrypted at rest;
            # open_plaintext is a no-op for plaintext / legacy files.
            from app.core.file_crypto import open_plaintext
            source_name = os.path.basename(str(file_path))
            with open_plaintext(str(file_path)) as plain_path:
                if ext == ".csv":
                    return await self._parse_csv(plain_path, params)
                elif ext in (".xlsx", ".xls"):
                    return await self._parse_excel(plain_path, params)
                elif ext == ".pdf":
                    return await self._parse_pdf(plain_path, params, source_name=source_name)
                else:
                    return {
                        "status": "error",
                        "error": f"Unsupported format: {ext}. Use .xlsx, .csv, or .pdf",
                    }
        except ImportError as e:
            return {
                "status": "error",
                "error": f"Missing dependency: {e}. Run: pip install pandas openpyxl pdfplumber",
            }
        except Exception as e:
            return {"status": "error", "error": f"Parse error: {e}"}

    async def _parse_csv(self, file_path: str, params: Dict) -> Dict:
        import pandas as pd
        df = pd.read_csv(file_path)
        return self._process_dataframe(df, params)

    async def _parse_excel(self, file_path: str, params: Dict) -> Dict:
        import pandas as pd
        sheet = params.get("sheet_name", 0)
        # Engine by format, not one-size: openpyxl reads only zip-based .xlsx,
        # so a hardcoded engine="openpyxl" made every legacy BIFF .xls die
        # with "File is not a zip file" while the block advertises ".xls".
        engine = "xlrd" if str(file_path).lower().endswith(".xls") else "openpyxl"
        # Real bills open with banner rows (project, employer, bill number),
        # so the column header is rarely row 0. Read headerless, find the
        # header by alias match, then promote it (a 12,971-row bill parsed
        # to ZERO items because row 0 was a title fragment).
        raw = pd.read_excel(file_path, sheet_name=sheet, engine=engine, header=None)
        hdr = self._detect_header_row(raw)
        df = raw.iloc[hdr + 1:].reset_index(drop=True)
        df.columns = [str(c).strip() for c in raw.iloc[hdr].tolist()]
        return self._process_dataframe(df, params)

    # How many leading rows to scan for the real column header. Contract
    # volumes open with project/employer/bill-number banner rows; 60 covers
    # every real bill seen while keeping the scan trivial.
    _HEADER_SCAN_ROWS = 60

    def _detect_header_row(self, df_raw) -> int:
        """Row index of the actual column header, or 0.

        A header row is the first row whose cells resolve to at least two
        DISTINCT canonical columns, one of which is `description`. Matching
        through _resolve_columns keeps this in lockstep with the alias map.
        """
        limit = min(self._HEADER_SCAN_ROWS, len(df_raw))
        for i in range(limit):
            cells = [str(c).strip() for c in df_raw.iloc[i].tolist()]
            resolved = self._resolve_columns(cells)
            if "description" in resolved and len(resolved) >= 2:
                return i
        return 0

    async def _parse_pdf(
        self, file_path: str, params: Dict, source_name: str = ""
    ) -> Dict:
        """Extract tabular BOQ data from a PDF via pdfplumber.

        Walks every page, calls ``page.extract_tables()``, treats row 0 of
        each table as a header, then groups tables by header signature so
        continuation pages with identical headers concatenate into a single
        DataFrame. The largest group is the BOQ and dispatches through
        ``_process_dataframe`` (same path Excel/CSV use).

        If no extractable tables exist (pure-image scan that wasn't OCR'd),
        returns raw page text with status "partial" so an LLM caller can
        extract line items, or an honest error when there is no text either.
        """
        # Memory guard: pdfplumber builds every page's table grid in memory;
        # on a large priced BOQ this can OOM the worker. Refuse cleanly.
        _PDF_MAX_MB = 32.0
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if size_mb > _PDF_MAX_MB:
            return {
                "status": "error",
                "error": (
                    f"This BOQ PDF is too large to parse on the server "
                    f"({size_mb:.1f} MB, limit {_PDF_MAX_MB:.0f} MB). PDF table "
                    f"extraction loads the whole file into memory and can crash "
                    f"the server. Please upload the .xlsx or .csv version of "
                    f"this BOQ instead."
                ),
                "boq_pdf_too_large": True,
                "size_mb": round(size_mb, 1),
                "max_mb": _PDF_MAX_MB,
            }

        import pdfplumber
        import pandas as pd

        groups: Dict[Tuple[str, ...], List[List[str]]] = {}
        primary_headers_for: Dict[Tuple[str, ...], List[str]] = {}
        page_table_count = 0
        pages_skipped = 0
        pages_skipped_reasons: List[Dict[str, Any]] = []

        with pdfplumber.open(file_path) as pdf:
            for page_index, page in enumerate(pdf.pages, 1):
                try:
                    tables = page.extract_tables() or []
                except Exception as exc:
                    logger.warning(
                        "boq_processor: page %s extract_tables failed: %s",
                        page_index,
                        exc,
                    )
                    pages_skipped += 1
                    pages_skipped_reasons.append({
                        "page": page_index,
                        "stage": "extract_tables",
                        "error": str(exc), "error_kind": error_kind(exc),
                    })
                    continue
                for tbl in tables:
                    if not tbl or len(tbl) < 2:
                        continue
                    headers_raw = [(str(c or "").strip()) for c in tbl[0]]
                    if not any(headers_raw):
                        continue
                    n_cols = len(headers_raw)
                    if n_cols < 2:
                        continue
                    key = tuple(self._normalize_col(h) for h in headers_raw)
                    norm_rows: List[List[str]] = []
                    for row in tbl[1:]:
                        if row is None:
                            continue
                        cells = [(str(c) if c is not None else "") for c in row]
                        if len(cells) < n_cols:
                            cells = cells + [""] * (n_cols - len(cells))
                        elif len(cells) > n_cols:
                            cells = cells[:n_cols]
                        if not any(s.strip() for s in cells):
                            continue
                        norm_rows.append(cells)
                    if not norm_rows:
                        continue
                    groups.setdefault(key, []).extend(norm_rows)
                    primary_headers_for.setdefault(key, headers_raw)
                    page_table_count += 1

        if not groups:
            # No clean table grid — normal for scanned BOQ PDFs. Return
            # per-page text so an LLM caller can extract line items.
            page_texts: List[Dict[str, Any]] = []
            with pdfplumber.open(file_path) as pdf:
                for i, page in enumerate(pdf.pages, 1):
                    try:
                        t = (page.extract_text() or "").strip()
                    except Exception as exc:
                        logger.warning(
                            "boq_processor: page %s extract_text failed: %s",
                            i,
                            exc,
                        )
                        pages_skipped += 1
                        pages_skipped_reasons.append({
                            "page": i,
                            "stage": "extract_text",
                            "error": str(exc), "error_kind": error_kind(exc),
                        })
                        t = ""
                    if t:
                        page_texts.append({"page": i, "text": t})
            if page_texts:
                return {
                    "status": "partial",
                    "source_format": "pdf",
                    "note": (
                        "PDF has no clean tabular structure (likely scanned). "
                        "Returning raw page text — pass to an LLM for BOQ "
                        "line-item extraction."
                    ),
                    "page_count": len(page_texts),
                    "page_texts": page_texts,
                    "pages_skipped": pages_skipped,
                    "pages_skipped_reasons": pages_skipped_reasons,
                }
            return {
                "status": "error",
                "error": (
                    "No extractable tables or text found in this PDF. The file "
                    "may be a pure-image scan that hasn't been OCR'd. Run OCR "
                    "first or re-upload as .xlsx/.csv."
                ),
                "pages_skipped": pages_skipped,
                "pages_skipped_reasons": pages_skipped_reasons,
            }

        best_key = max(groups.keys(), key=lambda k: len(groups[k]))
        df = pd.DataFrame(groups[best_key], columns=primary_headers_for[best_key])

        result = self._process_dataframe(df, params)
        if isinstance(result, dict):
            result.setdefault("source_format", "pdf")
            result["pdf_tables_total"] = page_table_count
            result["pdf_tables_used"] = len(groups[best_key])
            result["pages_skipped"] = pages_skipped
            result["pages_skipped_reasons"] = pages_skipped_reasons
        return result

    def _resolve_columns(self, columns: List[str]) -> Dict[str, str]:
        """Map alias-set field names to actual DataFrame column names.

        Two-pass: exact normalized match first (cheap, deterministic), then
        substring match against the same alias set as a fallback so columns
        like 'unit_rate_in_sar' still resolve when the prefix is recognised.
        """
        resolved: Dict[str, str] = {}
        normalized = [self._normalize_col(c) for c in columns]
        for field, candidates in self._COL_MAP.items():
            chosen_idx = None
            # Pass 1: exact normalized match.
            for c in candidates:
                if c in normalized:
                    chosen_idx = normalized.index(c)
                    break
            # Pass 2: substring match (longest alias first so "unit_rate" beats "unit").
            if chosen_idx is None:
                for c in sorted(candidates, key=len, reverse=True):
                    for i, ncol in enumerate(normalized):
                        if c in ncol.split("_") or ncol.startswith(c + "_") or ncol.endswith("_" + c):
                            chosen_idx = i
                            break
                    if chosen_idx is not None:
                        break
            if chosen_idx is not None:
                resolved[field] = columns[chosen_idx]
        return resolved

    @staticmethod
    def _normalize_col(name: str) -> str:
        """Reduce a raw column header to a canonical token for alias matching.

        Strips parenthesized suffixes (currency / unit hints) and trailing
        currency tokens, then lowercases and replaces spaces/slashes with
        underscores. Matches real BOQ headers like 'Rate (SAR)',
        'Amount (USD)', 'Qty.', 'Item No.' against the short alias list.
        """
        import re
        n = name.strip()
        n = re.sub(r"\s*\([^)]*\)\s*$", "", n)
        n = re.sub(
            r"[\s,;:]+(SAR|USD|AED|EUR|GBP|JPY|CNY|AUD|CAD|KWD|QAR|BHD|OMR)\b\.?$",
            "",
            n,
            flags=re.IGNORECASE,
        )
        n = n.rstrip(" .,:;")
        n = n.lower().replace(" ", "_").replace("/", "_").replace("-", "_")
        n = re.sub(r"_+", "_", n).strip("_")
        return n

    def _process_dataframe(self, df, params: Dict) -> Dict:
        df.columns = [str(c).strip() for c in df.columns]
        resolved = self._resolve_columns(list(df.columns))

        include_zero = params.get("include_zero_qty", self.config.get("include_zero_qty", False))
        currency = params.get("currency", self.config.get("currency", "USD"))

        line_items: List[Dict] = []
        section_totals: Dict[str, float] = {}

        for _, row in df.iterrows():
            description = str(row.get(resolved.get("description", ""), "")).strip()
            if not description or description.lower() == "nan":
                continue

            qty = _to_float(row.get(resolved.get("quantity", ""), 0))
            if not include_zero and qty == 0:
                continue

            rate = _to_float(row.get(resolved.get("rate", ""), 0))
            total = _to_float(row.get(resolved.get("total", ""), 0))
            if total == 0 and qty > 0 and rate > 0:
                total = qty * rate

            unit = str(row.get(resolved.get("unit", ""), "")).strip()
            section = str(row.get(resolved.get("section", ""), "General")).strip()
            if section.lower() == "nan":
                section = "General"

            item_key = description.lower().replace(" ", "_")[:50]

            line_items.append(
                {
                    "item_key": item_key,
                    "description": description,
                    "quantity": qty,
                    "unit": unit if unit != "nan" else "",
                    "unit_cost": rate,
                    "total_cost": round(total, 2),
                    "section": section,
                    "currency": currency,
                }
            )
            section_totals[section] = section_totals.get(section, 0.0) + total

        total_cost = sum(i["total_cost"] for i in line_items)
        cost_breakdown = {
            section: {
                "total": round(v, 2),
                "percentage": round(v / total_cost * 100, 1) if total_cost > 0 else 0,
            }
            for section, v in sorted(section_totals.items(), key=lambda x: x[1], reverse=True)
        }

        return {
            "status": "success",
            "item_count": len(line_items),
            "total_cost": round(total_cost, 2),
            "currency": currency,
            "line_items": line_items,
            "cost_breakdown": cost_breakdown,
            "sections": list(section_totals.keys()),
            "columns_detected": resolved,
        }


def _to_float(val) -> float:
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError) as exc:
        logger.debug("_to_float: unparseable value %r: %s", val, exc)
        return 0.0
