"""Review Reputation - deterministic two-sided reputation scoring.

Extends the review lifecycle (owned by the existing `review` block, which
handles CRUD and moderation) with marketplace reputation math: recency-
decayed weighted ratings, volume confidence smoothing, and deterministic
fraud weighting (duplicate text, same-pair floods, rating bursts). Pure
decision block: no network, no filesystem, no review storage.

A review record here is the scoring input {reviewer, reviewee, task_id,
rating, age_days, comment}; the block computes scores and flags. Storage
and moderation remain the `review` block's job (declared in requires).
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Dict, List, Optional, Tuple

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind

DEFAULT_HALF_LIFE_DAYS = 180.0
DEFAULT_PRIOR = 2.0  # Laplace smoothing: prior observations at neutral 3.0
NEUTRAL = 3.0


def decay_weight(age_days: float, half_life_days: float) -> float:
    """Recency weight: 1.0 today, halving every half-life."""
    if age_days < 0:
        age_days = 0.0
    return 0.5 ** (age_days / half_life_days)


class ReviewReputationBlock(UniversalBlock):
    """Deterministic reputation scoring with decay and fraud weighting."""

    name = "review_reputation"
    version = "1.0.0"
    description = (
        "Deterministic two-sided reputation scoring on top of the review "
        "block: recency-decayed weighted ratings, volume-confidence "
        "smoothing, and rule-based fraud weighting (duplicate comments, "
        "same-pair floods, rating bursts)."
    )
    layer = 3
    tags = ["domain", "marketplace", "reputation", "reviews", "deterministic"]
    requires = ["review"]
    author = "Cerebrum Team"
    default_config: Dict[str, Any] = {
        "half_life_days": DEFAULT_HALF_LIFE_DAYS,
        "prior_weight": DEFAULT_PRIOR,
        "fraud_max_same_pair": 3,
    }
    ui_schema = {
        "input": {"type": "json"},
        "output": {"type": "json"},
        "params": [],
        "quick_actions": [],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self.reviews: Dict[str, List[Dict[str, Any]]] = {}
        self.verdicts: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ api
    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        merged = {**params, **data}
        operation = merged.get("operation") or merged.get("action") or "submit"

        try:
            if operation == "submit":
                return self._submit(merged)
            if operation == "score":
                return self._score(merged)
            if operation == "aggregate":
                return self._aggregate(merged)
            if operation == "fraud_weight":
                return self._fraud_weight(merged)
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc), "operation": operation}

        return {
            "status": "error",
            "error": f"Unknown operation: {operation}",
            "available_operations": ["submit", "score", "aggregate", "fraud_weight"],
        }

    # -------------------------------------------------------------- helpers
    def _require(self, data: Dict[str, Any], keys: List[str]) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                return key
        return None

    def _rating(self, value: Any) -> float:
        try:
            rating = float(value)
        except (TypeError, ValueError):
            raise ValueError("rating: must be a number")
        if rating < 1.0 or rating > 5.0:
            raise ValueError("rating: must be within [1, 5]")
        return rating

    def _dup_key(self, review: Dict[str, Any]) -> str:
        raw = f"{review.get('reviewer')}|{review.get('reviewee')}|{review.get('task_id')}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    # ----------------------------------------------------------- operations
    def _submit(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["reviewer", "reviewee", "task_id", "rating"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        try:
            rating = self._rating(data["rating"])
        except ValueError as exc:
            return {"status": "error", "error": str(exc), "error_kind": error_kind(exc)}

        review = {
            "reviewer": data["reviewer"],
            "reviewee": data["reviewee"],
            "task_id": data["task_id"],
            "rating": rating,
            "age_days": float(data.get("age_days", 0.0)),
            "comment": data.get("comment") or "",
        }
        if data["reviewer"] == data["reviewee"]:
            return {"status": "error", "error": "self_review_refused"}

        bucket = self.reviews.setdefault(data["reviewee"], [])
        key = self._dup_key(review)
        if any(self._dup_key(r) == key for r in bucket):
            return {"status": "error", "error": "duplicate_review_refused"}

        bucket.append(review)
        verdict = self._fraud_weight_for(data["reviewee"])
        return {
            "status": "success",
            "operation": "submit",
            "reviewee": data["reviewee"],
            "review_count": len(bucket),
            "fraud_flags": verdict["flags"],
            "effective_weight": verdict["effective_weight"],
        }

    def _fraud_weight_for(self, reviewee: str) -> Dict[str, Any]:
        bucket = self.reviews.get(reviewee, [])
        flags: List[str] = []
        same_pair: Dict[str, int] = {}
        comment_counts: Dict[str, int] = {}
        max_pair = self.config.get("fraud_max_same_pair") or 3
        for review in bucket:
            pair = f"{review['reviewer']}|{review['task_id']}"
            same_pair[pair] = same_pair.get(pair, 0) + 1
            comment = (review.get("comment") or "").strip().lower()
            if comment:
                comment_counts[comment] = comment_counts.get(comment, 0) + 1
        if any(count > 1 for count in same_pair.values()):
            flags.append("same_pair_repeat")
        if any(count > 1 for count in comment_counts.values()):
            flags.append("duplicate_comment")
        if bucket:
            ratings = [r["rating"] for r in bucket]
            spread = max(ratings) - min(ratings)
            if len(bucket) >= 3 and spread <= 0.2 and sum(ratings) / len(ratings) > 4.5:
                flags.append("burst_high_ratings")
            if len(bucket) >= 3 and spread <= 0.2 and sum(ratings) / len(ratings) < 1.5:
                flags.append("burst_low_ratings")
        over = sum(1 for c in same_pair.values() if c > max_pair)
        effective = 1.0
        if flags:
            effective = max(0.25, 1.0 - 0.25 * len(flags) - 0.25 * over)
        return {"flags": flags, "effective_weight": round(effective, 4)}

    def _fraud_weight(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["reviewee"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        verdict = self._fraud_weight_for(data["reviewee"])
        return {
            "status": "success",
            "operation": "fraud_weight",
            "reviewee": data["reviewee"],
            **verdict,
        }

    def _score(self, data: Dict[str, Any]) -> Dict[str, Any]:
        missing = self._require(data, ["reviewee"])
        if missing:
            return {"status": "error", "error": f"missing_required_input: {missing}"}
        bucket = self.reviews.get(data["reviewee"], [])
        half_life = float(self.config.get("half_life_days") or DEFAULT_HALF_LIFE_DAYS)
        prior = float(self.config.get("prior_weight") or DEFAULT_PRIOR)
        verdict = self._fraud_weight_for(data["reviewee"])
        weight_total = prior
        rating_total = prior * NEUTRAL
        for review in bucket:
            weight = decay_weight(review["age_days"], half_life) * verdict["effective_weight"]
            weight_total += weight
            rating_total += weight * review["rating"]
        score = rating_total / weight_total
        return {
            "status": "success",
            "operation": "score",
            "reviewee": data["reviewee"],
            "score": round(score, 3),
            "review_count": len(bucket),
            "confidence": round(1.0 - prior / weight_total, 3),
            "half_life_days": half_life,
            "fraud_flags": verdict["flags"],
        }

    def _aggregate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        reviewees = data.get("reviewees")
        if not isinstance(reviewees, list) or not reviewees:
            return {"status": "error", "error": "aggregate requires a reviewees list"}
        scores = []
        for reviewee in reviewees:
            result = self._score({"reviewee": reviewee})
            if result["status"] == "success":
                scores.append(result)
        return {
            "status": "success",
            "operation": "aggregate",
            "scores": scores,
            "count": len(scores),
        }
