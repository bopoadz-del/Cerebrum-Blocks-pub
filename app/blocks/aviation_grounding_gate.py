"""Aviation Grounding Gate — safety-critical answer verifier.

Scope (enforced in code):
- READS: retrieved chunks, drafted answer, query
- WRITES: verdict only (pass / block / flag-as-estimate)
- NEVER: fabricates, alters, or infers numeric values; never invents citations;
  never mutates the answer text beyond attaching verdict/disclosure.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.typed_block import TypedBlock, Schema, ContentType


# Safety-critical domains: figures here must have explicit citations.
SAFETY_CRITICAL_DOMAINS = {"fare", "weight", "fuel", "capacity", "cargo", "revenue", "loyalty"}

# Units/currencies we recognise and normalise.
_WEIGHT_UNITS = {
    "kg", "kilogram", "kilograms",
    "lb", "lbs", "pound", "pounds",
    "ton", "tons", "tonne", "tonnes",
    "mt", "metric ton", "metric tons",
}
_FUEL_UNITS = {
    "l", "ltr", "litre", "litres", "liter", "liters",
    "us gal", "us gallon", "us gallons", "gal", "gallon", "gallons",
    "kg", "kilogram", "kilograms",
    "lb", "lbs",
}
_CURRENCY_UNITS = {
    "sar", "usd", "eur", "gbp", "aed", "qar", "bhd", "kwd", "omr",
    "$", "€", "£", "﷼",
}
_CAPACITY_UNITS = {
    "pax", "passenger", "passengers", "seat", "seats",
    "kg", "kilogram", "kilograms", "lb", "lbs", "ton", "tons",
}
_RATIO_UNITS = {
    "%", "percent", "percentage", "pct",
}
_LOYALTY_UNITS = {
    "miles", "mile", "points", "point",
}
_TIME_UNITS = {
    "hour", "hours", "hr", "hrs",
    "minute", "minutes", "min", "mins",
    "second", "seconds", "sec", "secs",
}

_UNIT_CATEGORY_MAP = {
    "weight": _WEIGHT_UNITS,
    "fuel": _FUEL_UNITS,
    "fare": _CURRENCY_UNITS,
    "capacity": _CAPACITY_UNITS,
    "cargo": _WEIGHT_UNITS | _FUEL_UNITS | _CAPACITY_UNITS,
    "ratio": _RATIO_UNITS,
    "loyalty": _LOYALTY_UNITS,
    "time": _TIME_UNITS,
}


class AviationGroundingGateBlock(TypedBlock):
    """Safety-critical grounding gate for aviation answers.

    Returns a verdict and, if allowed, the original answer decorated with
    mandatory disclosures.  The answer text is never rewritten or interpolated
    with document content.
    """

    name = "aviation_grounding_gate"
    version = "1.0.0"
    description = (
        "Safety-critical grounding gate: every figure must trace to a "
        "retrieved chunk with matching unit/currency semantics."
    )
    layer = 3
    tags = ["aviation", "safety", "grounding", "citations", "compliance"]
    requires = []

    input_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=["answer", "citations", "query"],
        optional_fields=["query_type", "confidence_threshold", "domain_context"],
        format_hints={},
    )

    output_schema = Schema(
        content_type=ContentType.JSON,
        required_fields=["status", "verdict"],
        optional_fields=[
            "allowed_response",
            "blocked_reason",
            "required_disclaimers",
            "figure_checks",
            "citation_coverage",
        ],
        format_hints={},
    )

    default_config = {
        "confidence_threshold": 0.75,
        "flag_threshold": 0.5,
        "require_citations_for": list(SAFETY_CRITICAL_DOMAINS),
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"answer": "...", "citations": [...], "query": "..."}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "verdict", "type": "text", "label": "Verdict"},
                {"name": "allowed_response", "type": "text", "label": "Allowed Response"},
                {"name": "blocked_reason", "type": "text", "label": "Blocked Reason"},
            ],
        },
        "quick_actions": [
            {"icon": "🛡", "label": "Ground answer", "prompt": "Check this aviation answer for grounding."},
        ],
    }

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}

        answer = data.get("answer", "")
        citations = data.get("citations", []) or []
        query = data.get("query", "")
        query_type = (data.get("query_type") or params.get("query_type") or "general").lower()
        threshold = float(
            data.get("confidence_threshold")
            or params.get("confidence_threshold")
            or self.config.get("confidence_threshold", 0.75)
        )
        flag_threshold = float(self.config.get("flag_threshold", 0.5))

        if not answer and not query:
            return {
                "status": "error",
                "verdict": "block",
                "blocked_reason": "Missing answer and query.",
            }

        # Decide whether this query type is safety-critical.
        is_safety_critical = query_type in SAFETY_CRITICAL_DOMAINS or any(
            term in query.lower() for term in SAFETY_CRITICAL_DOMAINS
        )

        # Build a single corpus string from citations for fast substring checks.
        corpus_text = "\n".join(_chunk_text(c) for c in citations).lower()

        # Extract candidate figures from the answer.
        figures = _extract_figures(answer)

        figure_checks: List[Dict[str, Any]] = []
        worst_verdict = "pass"
        blocked_reasons: List[str] = []

        for figure in figures:
            check = self._check_figure(figure, corpus_text, threshold)
            figure_checks.append(check)
            verdict = check["verdict"]
            if verdict == "block":
                worst_verdict = "block"
                blocked_reasons.append(check["reason"])
            elif verdict == "flag-as-estimate" and worst_verdict != "block":
                worst_verdict = "flag-as-estimate"

        # If there are no figures but the query is safety-critical and asks for
        # a figure, we must block/flag because the answer failed to deliver a
        # grounded number.
        if is_safety_critical and not figures and _implies_numeric_answer(query):
            worst_verdict = "block"
            blocked_reasons.append(
                "Safety-critical query expects a numeric figure, but none was found in the answer."
            )

        # Compute citation coverage as a simple presence metric.
        citation_coverage = self._citation_coverage(answer, citations)

        required_disclaimers = ["Verify before operational use."]
        if worst_verdict == "flag-as-estimate":
            required_disclaimers.append(
                "This answer contains estimates or figures with weak citation coverage."
            )

        if worst_verdict == "block":
            return {
                "status": "success",
                "verdict": "block",
                "allowed_response": None,
                "blocked_reason": " ".join(blocked_reasons) or "Grounding gate blocked the answer.",
                "required_disclaimers": required_disclaimers,
                "figure_checks": figure_checks,
                "citation_coverage": citation_coverage,
            }

        # Pass or flag-as-estimate: decorate the original answer with verdict
        # and disclosures.  We do NOT rewrite or interpolate answer content.
        decorated = _decorate_answer(answer, worst_verdict, required_disclaimers)

        return {
            "status": "success",
            "verdict": worst_verdict,
            "allowed_response": decorated,
            "blocked_reason": None,
            "required_disclaimers": required_disclaimers,
            "figure_checks": figure_checks,
            "citation_coverage": citation_coverage,
        }

    # ------------------------------------------------------------------
    # Internal checks
    # ------------------------------------------------------------------

    def _check_figure(
        self, figure: Dict[str, Any], corpus_text: str, threshold: float
    ) -> Dict[str, Any]:
        """Return a verdict for a single extracted figure."""
        value = figure["value"]
        unit = figure.get("unit")
        category = _unit_category(unit)

        # Normalise corpus so "$2,500", "2,500", and "2500" match each other.
        normalised_corpus = _normalise_corpus(corpus_text)

        # Search the corpus for the raw value.
        value_in_corpus = _value_present(value, corpus_text) or _value_present(
            value, normalised_corpus
        )

        # Search for value near compatible units.
        unit_compatible = False
        if unit and category:
            unit_compatible = _unit_compatible_in_corpus(
                value, unit, category, corpus_text
            ) or _unit_compatible_in_corpus(value, unit, category, normalised_corpus)

        # Build an evidence score.
        score = 0.0
        if value_in_corpus:
            score += 0.5
        if unit_compatible:
            score += 0.5

        if score >= threshold:
            verdict = "pass"
            reason = "Figure is supported by retrieved chunks."
        elif score >= self.config.get("flag_threshold", 0.5):
            verdict = "flag-as-estimate"
            reason = (
                f"Figure {value} has weak citation coverage "
                f"(unit={unit}, category={category or 'unknown'})."
            )
        else:
            verdict = "block"
            reason = (
                f"Figure {value} could not be traced to a retrieved chunk "
                f"with matching unit/currency semantics (unit={unit})."
            )

        return {
            "figure": figure,
            "value_in_corpus": value_in_corpus,
            "unit_compatible": unit_compatible,
            "score": round(score, 3),
            "verdict": verdict,
            "reason": reason,
        }

    def _citation_coverage(self, answer: str, citations: List[Any]) -> Dict[str, Any]:
        """Return a coarse coverage metric (not a substitute for figure checks)."""
        citation_texts = [_chunk_text(c) for c in citations]
        tokens = set(re.findall(r"\b\w+\b", answer.lower()))
        if not tokens:
            return {"answer_tokens": 0, "cited_tokens": 0, "coverage_ratio": 0.0}

        cited_tokens = set()
        for text in citation_texts:
            text_tokens = set(re.findall(r"\b\w+\b", text.lower()))
            cited_tokens.update(tokens & text_tokens)

        return {
            "answer_tokens": len(tokens),
            "cited_tokens": len(cited_tokens),
            "coverage_ratio": round(len(cited_tokens) / len(tokens), 3),
        }


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _chunk_text(citation: Any) -> str:
    """Normalise a citation object or string to plain text."""
    if isinstance(citation, str):
        return citation
    if isinstance(citation, dict):
        return citation.get("text", citation.get("content", ""))
    return str(citation)


def _extract_figures(text: str) -> List[Dict[str, Any]]:
    """Extract numeric figures with optional units from text.

    Handles units/currency symbols both before and after the number,
    e.g. "$2,500" and "2,500 SAR".
    """
    figures: List[Dict[str, Any]] = []

    currency_symbols = r"\$|€|£|﷼"
    currency_codes = r"USD|EUR|GBP|SAR|AED|QAR|BHD|KWD|OMR"
    physical_units = r"kg|lbs?|tons?|tonnes?|pax|passengers?|seats?|litres?|liters?|gallons?|gal|ltrs?"
    ratio_units = r"%|pct|percent|percentage"
    loyalty_units = r"miles?|points?"
    time_units = r"hours?|hrs?|minutes?|mins?|seconds?|secs?"

    # Number with optional thousands separator and decimal.
    value_re = r"[+-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\.\d+"
    unit_re = f"(?:{currency_codes}|{currency_symbols}|{physical_units}|{ratio_units}|{loyalty_units}|{time_units})"

    # Pattern: optional leading unit, value, optional trailing unit.
    pattern = re.compile(
        rf"(?P<pre_unit>{unit_re})?\s*(?P<value>{value_re})\s*(?P<post_unit>{unit_re})?",
        re.IGNORECASE,
    )

    for match in pattern.finditer(text):
        raw_value = match.group("value").replace(",", "")
        try:
            value = float(raw_value)
        except ValueError:
            continue

        # Skip bare integers that are likely years, counts in prose, etc.
        if value.is_integer() and 1900 <= value <= 2100:
            continue

        # Skip fiscal periods (Q1, Q2, H1, H2) and ordinals (1st, 2nd, 3rd).
        start = match.start()
        prefix = text[start - 1 : start] if start > 0 else ""
        suffix = text[match.end() : match.end() + 2] if match.end() < len(text) else ""
        if prefix.upper() in {"Q", "H"}:
            continue
        if suffix.lower() in {"st", "nd", "rd", "th"}:
            continue

        # Prefer trailing unit; fall back to leading unit.
        unit = (match.group("post_unit") or match.group("pre_unit") or "").strip().lower()

        figures.append({
            "value": value,
            "raw": match.group("value"),
            "unit": unit or None,
            "span": match.span(),
        })

    return figures


def _unit_category(unit: Optional[str]) -> Optional[str]:
    """Map a unit string to a high-level category."""
    if not unit:
        return None
    unit_norm = unit.lower().strip()
    for category, units in _UNIT_CATEGORY_MAP.items():
        if unit_norm in units:
            return category
    return None


def _value_present(value: float, corpus_text: str) -> bool:
    """Check whether the numeric value appears in the corpus."""
    str_value = _format_value(value)
    return str_value in corpus_text


def _unit_compatible_in_corpus(
    value: float, unit: str, category: str, corpus_text: str
) -> bool:
    """Check whether value appears near a compatible unit in the corpus.

    Uses a positional window check so currency symbols (e.g. "$") and
    comma-formatted numbers do not fail on regex word-boundary rules.
    """
    str_value = _format_value(value)
    compatible_units = _UNIT_CATEGORY_MAP.get(category, set())
    lower_text = corpus_text.lower()
    normalised_text = _normalise_corpus(corpus_text)

    for compat in compatible_units:
        # Find every occurrence of the compatible unit in the original text.
        start = 0
        while True:
            idx = lower_text.find(compat, start)
            if idx == -1:
                break
            window_start = max(0, idx - 50)
            window_end = min(len(lower_text), idx + len(compat) + 50)
            window = lower_text[window_start:window_end]
            normalised_window = _normalise_corpus(window)
            if str_value in window or str_value in normalised_window:
                return True
            start = idx + len(compat)

        # Also find every occurrence of the value and check for a nearby unit.
        start = 0
        while True:
            idx = normalised_text.find(str_value, start)
            if idx == -1:
                break
            window_start = max(0, idx - 50)
            window_end = min(len(normalised_text), idx + len(str_value) + 50)
            window = normalised_text[window_start:window_end]
            if compat in window:
                return True
            start = idx + len(str_value)

    return False


def _format_value(value: float) -> str:
    """Format a value the same way it likely appears in text."""
    if value.is_integer():
        return str(int(value))
    return str(value)


def _normalise_corpus(text: str) -> str:
    """Return a stripped version of corpus text for fuzzy value matching.

    Removes common currency symbols and thousands separators so "$2,500",
    "2,500", and "2500" all collapse to the same searchable form.
    """
    text = text.lower()
    # Drop currency symbols (ASCII and Arabic riyal sign).
    text = re.sub(r"[\$\€\£\﷼]", "", text)
    # Strip thousands separators.
    text = text.replace(",", "")
    return text


def _implies_numeric_answer(query: str) -> bool:
    """Heuristic: does the query ask for a figure?"""
    keywords = [
        "how much", "what is the fare", "price", "cost", "weight", "fuel",
        "capacity", "how many seats", "passengers", "cargo", "load factor",
        "yield", "revenue",
    ]
    q = query.lower()
    return any(kw in q for kw in keywords)


def _decorate_answer(answer: str, verdict: str, disclaimers: List[str]) -> str:
    """Attach verdict and disclosures without mutating answer content."""
    suffix_parts = [f"[grounding_verdict={verdict}]"]
    for disclaimer in disclaimers:
        suffix_parts.append(f"[disclaimer: {disclaimer}]")
    suffix = "\n\n" + "\n".join(suffix_parts)
    return answer + suffix
