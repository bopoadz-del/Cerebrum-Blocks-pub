"""Confidence scoring helpers for extraction blocks.

Mirrors the interface expected by ``construction_v2.py`` and other
TypedBlock extraction pipelines. Keeps scoring deterministic and fast.
"""

from typing import Any, Dict, List, Optional


def _is_meaningful(value: Any) -> bool:
    """Return True if a value contains real extracted data (not placeholder/empty)."""
    if value is None:
        return False
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if not cleaned:
            return False
        return cleaned not in {"n/a", "na", "none", "unknown", "null", "missing", "--", "-"}
    if isinstance(value, (list, tuple)):
        return any(_is_meaningful(item) for item in value)
    if isinstance(value, dict):
        if not value:
            return False
        return any(_is_meaningful(v) for v in value.values())
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return value != 0
    return True


def _score_value(value: Any) -> float:
    """Score a single field value 0-1 based on content quality."""
    if not _is_meaningful(value):
        return 0.0

    if isinstance(value, list):
        meaningful = [item for item in value if _is_meaningful(item)]
        if not meaningful:
            return 0.0
        # Reward up to 5 meaningful items, then cap.
        return round(min(1.0, len(meaningful) / 5.0), 2)

    if isinstance(value, dict):
        meaningful = {k: v for k, v in value.items() if _is_meaningful(v)}
        if not meaningful:
            return 0.0
        return round(min(1.0, len(meaningful) / 3.0), 2)

    if isinstance(value, str):
        # Slight boost for longer strings (more extracted content).
        return round(min(1.0, 0.6 + len(value.strip()) / 500.0), 2)

    # Numbers, booleans, etc.
    return 1.0


def assess_extraction_confidence(
    result: Dict[str, Any],
    expected_fields: List[str],
    ocr_quality: Optional[float] = None,
) -> Dict[str, Any]:
    """Score how well an extraction result populated expected fields.

    Args:
        result: The extraction result dict.
        expected_fields: Field names that should be present and non-empty.
        ocr_quality: Optional 0-1 quality score to blend in.

    Returns:
        Dict with ``overall`` confidence (0-1), ``field_scores``,
        and ``ocr_quality``.
    """
    scores: List[float] = []
    field_scores: Dict[str, float] = {}

    for field in expected_fields:
        score = _score_value(result.get(field))
        scores.append(score)
        field_scores[field] = round(score, 2)

    overall = sum(scores) / len(scores) if scores else 0.0
    if ocr_quality is not None:
        overall = overall * 0.7 + max(0.0, min(1.0, ocr_quality)) * 0.3

    return {
        "overall": round(overall, 2),
        "field_scores": field_scores,
        "ocr_quality": ocr_quality,
    }
