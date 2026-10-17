"""Learning Engine Block - Tier promotion + coefficient tuning via scikit-learn"""

import logging
import time
from typing import Any, Dict, List, Optional
from app.core.universal_base import UniversalBlock
from app.core.block_config import Config
from app.core.learning_store import MemoryLearningStore
from app.core.credibility import (
    CredibilityRecord,
    CredibilityScorer,
    CredibilityTier,
)

logger = logging.getLogger(__name__)

# Tier thresholds: (min_executions, max_mae_pct) → tier label
_TIER_RULES = [
    (0,   "bronze"),   # new formulas start here
    (10,  "silver"),   # enough samples to train
    (50,  "gold"),     # good convergence
    (200, "platinum"), # high confidence
]


class LearningEngineBlock(UniversalBlock):
    name = "learning_engine"
    version = "1.0.0"
    description = "Tier promotion + coefficient tuning: learns from user corrections to improve formula accuracy"
    layer = 3
    tags = ["domain", "construction", "ml", "learning", "coefficients", "tier"]
    requires = []

    default_config = {
        "promotion_mae_threshold": 0.05,   # 5% MAE to promote
        "min_samples_for_training": 5,
        # No storage_path. The backend is injected via config
        # (``storage_backend``). A local file path in a block is the
        # thing KERNEL_DEFAULTS 1.5 exists to stop.
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"correction_data": {"formula_id": "concrete_cost", "predicted": 125000, "actual": 118000}, "operation": "record_correction"}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "tier_level", "type": "text", "label": "Tier"},
                {"name": "updated_coefficients", "type": "json", "label": "Coefficients"},
                {"name": "promotion_flag", "type": "boolean", "label": "Promoted"},
            ],
        },
        "quick_actions": [
            {"icon": "📈", "label": "Check Tier", "prompt": "Show tier levels for all formulas"},
            {"icon": "🔧", "label": "Tune", "prompt": "Tune coefficients from latest corrections"},
            {"icon": "📊", "label": "Performance", "prompt": "Show model performance metrics"},
        ],
    }

    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self._memory_store: Optional[MemoryLearningStore] = None
        self._state: Dict = self._load_state()
        # Shared credibility scorer — pure functions; safe to memoise.
        self._credibility_scorer = CredibilityScorer()

    @property
    def settings(self) -> Config:
        """The settings this block was HANDED. No ``os.getenv`` in this module."""
        return Config(self.config)

    @property
    def _store(self):
        """The storage backend this block was given, or the memory fallback.

        Resolution, in order, and all of it injected:

        1. ``storage_backend`` — an object with ``load`` / ``save``. This is
           what makes durability testable without the block choosing a path.
        2. An in-process :class:`MemoryLearningStore`. Visible as the
           fallback rung; lost on restart.
        """
        backend = self.settings.get("storage_backend")
        if backend is not None:
            return backend
        if self._memory_store is None:
            self._memory_store = MemoryLearningStore()
        return self._memory_store

    # ── credibility helpers ────────────────────────────────────────────

    def _credibility_record(self, formula_id: str) -> CredibilityRecord:
        """Load or initialise the CredibilityRecord for ``formula_id``."""
        formula = self._state["formulas"].setdefault(formula_id, {
            "samples": [],
            "tier": "bronze",
            "coefficients": {"bias": 0.0, "scale": 1.0},
            "executions": 0,
            "created_at": time.time(),
        })
        cred = formula.get("credibility")
        if isinstance(cred, dict) and cred.get("item_id"):
            try:
                return CredibilityRecord.from_dict(cred)
            except Exception:
                pass
        return CredibilityRecord(item_id=formula_id)

    def _sample_count(self, formula_id: str) -> int:
        """Number of recorded correction samples for ``formula_id``."""
        formula = self._state.get("formulas", {}).get(formula_id) or {}
        return len(formula.get("samples", []))

    def get_correction_history(self, formula_id: str) -> List[Dict]:
        """Return the raw correction samples (predicted/actual/ts) for
        ``formula_id``. Public so the retrain Celery task can pull it."""
        formula = self._state.get("formulas", {}).get(formula_id) or {}
        return list(formula.get("samples", []))

    def set_coefficients(self, formula_id: str, coefficients: Dict[str, float]) -> None:
        """Persist ``coefficients`` for ``formula_id``. Used by the
        retrain task to commit a new fit."""
        formula = self._state.setdefault("formulas", {}).setdefault(formula_id, {
            "samples": [],
            "tier": "bronze",
            "coefficients": {},
            "executions": 0,
            "created_at": time.time(),
        })
        formula["coefficients"] = dict(coefficients)
        self._save_state()

    def get_coefficient_mae(self, formula_id: str, history: List[Dict]) -> Optional[float]:
        """Return the MAE of the currently-stored coefficients evaluated
        against ``history``. Returns ``None`` when no usable coefficients
        are persisted yet (the retrain task treats that as "any fit is
        an improvement")."""
        formula = self._state.get("formulas", {}).get(formula_id) or {}
        coeffs = formula.get("coefficients") or {}
        scale = float(coeffs.get("scale", coeffs.get("multiplier", 1.0) or 1.0))
        bias = float(coeffs.get("bias", 0.0))
        errs: List[float] = []
        for h in history:
            try:
                p = float(h.get("predicted", 0))
                a = float(h.get("actual", 0))
            except (TypeError, ValueError):
                continue
            errs.append(abs((p * scale + bias) - a))
        if not errs:
            return None
        return sum(errs) / len(errs)

    @staticmethod
    def _accuracy_from_samples(samples: List[Dict]) -> float:
        """Compute rolling accuracy in [0, 1] from predicted/actual pairs.

        Defined as ``1 - MAPE`` (mean absolute percentage error), clamped.
        Empty samples → 0.0 so it doesn't masquerade as perfect.
        """
        if not samples:
            return 0.0
        errs: List[float] = []
        for s in samples:
            try:
                p = float(s["predicted"])
                a = float(s["actual"])
            except (KeyError, TypeError, ValueError):
                continue
            if a == 0:
                # Avoid divide-by-zero; treat as exact when both are 0.
                errs.append(0.0 if p == 0 else 1.0)
            else:
                errs.append(min(1.0, abs(a - p) / abs(a)))
        if not errs:
            return 0.0
        mape = sum(errs) / len(errs)
        return max(0.0, min(1.0, 1.0 - mape))

    def _update_credibility(self, formula_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """Recompute and persist the credibility record for ``formula_id``.

        Returns a dict shaped for the action response:
            {tier, previous_tier, accuracy, sample_size, promoted}
        """
        formula = self._state["formulas"][formula_id]
        record = self._credibility_record(formula_id)
        previous_tier = record.tier

        accuracy = self._accuracy_from_samples(formula.get("samples", []))
        sample_size = len(formula.get("samples", []))
        record = self._credibility_scorer.evaluate_promotion(
            record, accuracy, sample_size, reason=reason,
        )
        formula["credibility"] = record.to_dict()
        promoted = (
            int(record.tier) < int(previous_tier)
            if previous_tier is not None else False
        )
        return {
            "tier": record.tier.name,
            "tier_value": int(record.tier),
            "previous_tier": previous_tier.name,
            "previous_tier_value": int(previous_tier),
            "accuracy": record.accuracy,
            "sample_size": record.sample_size,
            "promoted": record.tier != previous_tier,  # True on either direction change
            "promoted_up": promoted,
        }

    def _load_state(self) -> Dict:
        try:
            loaded = self._store.load()
        except Exception:
            return {"formulas": {}, "history": []}
        if isinstance(loaded, dict):
            loaded.setdefault("formulas", {})
            loaded.setdefault("history", [])
            return loaded
        return {"formulas": {}, "history": []}

    def _save_state(self):
        try:
            self._store.save(self._state)
        except Exception:
            pass

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}

        # Default to "status" when called with bare text (no structured correction data)
        has_correction_data = data.get("formula_id") or data.get("correction_data") or params.get("formula_id")
        default_op = "record_correction" if has_correction_data else "status"
        operation = data.get("operation") or params.get("operation") or (data.get("text") or data.get("input") or "").strip() or default_op

        if operation == "record_correction":
            return await self._record_correction(data, params)
        elif operation == "tune":
            return await self._tune_coefficients(data, params)
        elif operation == "promote":
            return await self._evaluate_promotion(data, params)
        elif operation == "status":
            return self._get_status()
        elif operation == "reset":
            formula_id = data.get("formula_id") or params.get("formula_id")
            return self._reset_formula(formula_id)
        else:
            return {"status": "error", "error": f"Unknown operation: {operation}. Use: record_correction, tune, promote, status, reset"}

    async def _record_correction(self, data: Dict, params: Dict) -> Dict:
        correction = data.get("correction_data", {})
        formula_id = correction.get("formula_id") or data.get("formula_id") or params.get("formula_id")
        predicted = correction.get("predicted") or data.get("predicted")
        actual = correction.get("actual") or data.get("actual")

        if not formula_id:
            return {"status": "error", "error": "formula_id required"}
        if predicted is None or actual is None:
            return {"status": "error", "error": "predicted and actual values required"}

        predicted = float(predicted)
        actual = float(actual)

        if formula_id not in self._state["formulas"]:
            self._state["formulas"][formula_id] = {
                "samples": [],
                "tier": "bronze",
                "coefficients": {"bias": 0.0, "scale": 1.0},
                "executions": 0,
                "created_at": time.time(),
            }

        formula = self._state["formulas"][formula_id]
        formula["samples"].append({"predicted": predicted, "actual": actual, "ts": time.time()})
        formula["executions"] += 1
        self._save_state()

        # Auto-tune if enough samples
        min_samples = int(self.config.get("min_samples_for_training", 5))
        tuned = False
        if len(formula["samples"]) >= min_samples:
            coefficients, mae = self._fit_linear(formula["samples"])
            formula["coefficients"] = coefficients
            formula["last_mae"] = mae
            tuned = True

        tier, promoted = self._compute_tier(formula)
        if promoted:
            formula["tier"] = tier

        # ── credibility + drift detection ─────────────────────────────
        # Snapshot the credibility record BEFORE recompute so we can:
        #   1. compare current accuracy against accuracy_at_promotion
        #   2. detect tier transitions (record.tier vs updated.tier)
        # `_credibility_record` returns a fresh CredibilityRecord copy
        # built from persisted state — mutating it is safe.
        record_before = self._credibility_record(formula_id)
        previous_tier = record_before.tier
        # Capture the pre-evaluation baseline because evaluate_promotion
        # rewrites accuracy_at_promotion on tier change.
        baseline_at_promotion = record_before.accuracy_at_promotion

        new_accuracy = self._accuracy_from_samples(formula.get("samples", []))
        new_sample_size = self._sample_count(formula_id)

        # `detect_drift` gates on `record.sample_size`. The persisted
        # record carries the previous eval's sample count; bump it to
        # `max(persisted, current)` so a stream of fresh corrections
        # actually counts toward the min_samples floor without losing
        # prior history that lived in `formula["credibility"]`.
        if new_sample_size > record_before.sample_size:
            record_before.sample_size = new_sample_size
        drift_detected = self._credibility_scorer.detect_drift(
            record_before, new_accuracy,
        )

        # Recompute tier with the latest stats (mutates record_before).
        updated = self._credibility_scorer.evaluate_promotion(
            record_before, new_accuracy, new_sample_size,
            reason="correction recorded",
        )
        formula["credibility"] = updated.to_dict()

        if drift_detected:
            self._handle_drift_event(
                formula_id=formula_id,
                baseline_accuracy=baseline_at_promotion,
                new_accuracy=new_accuracy,
                new_sample_size=new_sample_size,
                tier_before=previous_tier,
                tier_after=updated.tier,
            )

            if updated.tier > CredibilityTier.OPERATIONAL:
                self._enqueue_retrain(formula_id)

        self._save_state()

        return {
            "status": "success",
            "formula_id": formula_id,
            "tier_level": formula["tier"],
            "updated_coefficients": formula["coefficients"],
            "promotion_flag": promoted,
            "sample_count": len(formula["samples"]),
            "auto_tuned": tuned,
            "credibility": {
                "tier": str(updated.tier),
                "tier_name": updated.tier.name,
                "previous_tier": str(previous_tier),
                "previous_tier_name": previous_tier.name,
                "accuracy": new_accuracy,
                "sample_size": new_sample_size,
                "drift_detected": drift_detected,
                "promoted": updated.tier != previous_tier,
            },
        }

    def _handle_drift_event(
        self,
        *,
        formula_id: str,
        baseline_accuracy: float,
        new_accuracy: float,
        new_sample_size: int,
        tier_before: CredibilityTier,
        tier_after: CredibilityTier,
    ) -> None:
        """Persist a drift event and forward to MLflow.

        Both writes are best-effort: MLflow is no-op when not configured,
        and state writes are wrapped because callers must never have a
        correction-recording flow fail because of a logging side effect.
        """
        try:
            from app.core.mlflow_tracker import tracker
            with tracker.start_run(f"drift-{formula_id}"):
                tracker.log_metrics({
                    "accuracy_at_promotion": float(baseline_accuracy),
                    "current_accuracy": float(new_accuracy),
                    "drift_delta": float(baseline_accuracy) - float(new_accuracy),
                    "sample_size": float(new_sample_size),
                })
                tracker.log_param("formula_id", formula_id)
                tracker.log_param("tier_before", str(tier_before))
                tracker.log_param("tier_after", str(tier_after))
        except Exception:
            logger.exception("learning: MLflow drift logging failed")

        # Persist into learning_state.json so operators can audit drift
        # without a separate event store.
        self._state.setdefault("drift_events", []).append({
            "formula_id": formula_id,
            "at": time.time(),
            "from_accuracy": float(baseline_accuracy),
            "to_accuracy": float(new_accuracy),
            "tier_before": str(tier_before),
            "tier_after": str(tier_after),
        })
        self._save_state()

    def _enqueue_retrain(self, formula_id: str) -> None:
        """Best-effort retrain enqueue.

        When Celery is wired and the broker is reachable, ``.delay()``
        ships the task. When it isn't (CI, local dev without Redis),
        record the formula_id in a ``pending_retrains`` queue inside the
        learning state file so an operator/cron job can pick them up
        later. Either way, never raise — drift handling must not break
        correction recording.
        """
        try:
            from app.tasks.learning_retrain import retrain_formula
            retrain_formula.delay(formula_id)
        except Exception:
            logger.exception("learning: retrain enqueue failed; recording as pending")
            self._state.setdefault("pending_retrains", []).append({
                "formula_id": formula_id,
                "at": time.time(),
            })
            self._save_state()

    async def _tune_coefficients(self, data: Dict, params: Dict) -> Dict:
        formula_id = data.get("formula_id") or params.get("formula_id")
        execution_history = data.get("execution_history", [])

        targets = [formula_id] if formula_id else list(self._state["formulas"].keys())
        results = {}

        for fid in targets:
            if fid not in self._state["formulas"]:
                continue
            formula = self._state["formulas"][fid]
            samples = formula["samples"] + execution_history
            if len(samples) < 2:
                results[fid] = {"skipped": True, "reason": "insufficient samples"}
                continue
            coefficients, mae = self._fit_linear(samples)
            formula["coefficients"] = coefficients
            formula["last_mae"] = mae
            tier, promoted = self._compute_tier(formula)
            if promoted:
                formula["tier"] = tier
            results[fid] = {
                "coefficients": coefficients,
                "mae": mae,
                "tier_level": formula["tier"],
                "promotion_flag": promoted,
            }

        self._save_state()
        return {
            "status": "success",
            "tune_results": results,
            "formulas_tuned": len(results),
            "tier_level": list({v.get("tier_level", "") for v in results.values() if isinstance(v, dict)}),
            "updated_coefficients": {k: v.get("coefficients", {}) for k, v in results.items()},
            "promotion_flag": any(v.get("promotion_flag") for v in results.values() if isinstance(v, dict)),
        }

    async def _evaluate_promotion(self, data: Dict, params: Dict) -> Dict:
        formula_id = data.get("formula_id") or params.get("formula_id")
        results = {}
        targets = [formula_id] if formula_id else list(self._state["formulas"].keys())

        for fid in targets:
            if fid not in self._state["formulas"]:
                continue
            formula = self._state["formulas"][fid]
            old_tier = formula["tier"]
            tier, promoted = self._compute_tier(formula)
            if promoted:
                formula["tier"] = tier
            credibility = self._update_credibility(fid, reason="promotion eval")
            results[fid] = {
                "old_tier": old_tier,
                "new_tier": formula["tier"],
                "promoted": promoted,
                "executions": formula["executions"],
                "sample_count": len(formula["samples"]),
                "credibility": credibility,
            }

        self._save_state()
        return {
            "status": "success",
            "promotion_results": results,
            "tier_level": list({v["new_tier"] for v in results.values()}),
            "updated_coefficients": {},
            "promotion_flag": any(v["promoted"] for v in results.values()),
            "credibility_promotion_flag": any(
                v["credibility"]["promoted"] for v in results.values()
            ),
        }

    def _get_status(self) -> Dict:
        summary = {}
        credibility_dist: Dict[str, int] = {}
        for fid, formula in self._state["formulas"].items():
            cred = formula.get("credibility") or {}
            summary[fid] = {
                "tier": formula["tier"],
                "executions": formula["executions"],
                "samples": len(formula["samples"]),
                "coefficients": formula["coefficients"],
                "last_mae": formula.get("last_mae"),
                "credibility": cred,
            }
            cred_name = cred.get("tier_name")
            if cred_name:
                credibility_dist[cred_name] = credibility_dist.get(cred_name, 0) + 1
        tier_dist: Dict[str, int] = {}
        for f in self._state["formulas"].values():
            t = f["tier"]
            tier_dist[t] = tier_dist.get(t, 0) + 1
        return {
            "status": "success",
            "total_formulas": len(self._state["formulas"]),
            "tier_distribution": tier_dist,
            "credibility_distribution": credibility_dist,
            "formula_summary": summary,
            "tier_level": list(tier_dist.keys()),
            "updated_coefficients": {},
            "promotion_flag": False,
        }

    def _reset_formula(self, formula_id: Optional[str]) -> Dict:
        if not formula_id:
            return {"status": "error", "error": "formula_id required for reset"}
        if formula_id in self._state["formulas"]:
            del self._state["formulas"][formula_id]
            self._save_state()
        return {
            "status": "success",
            "formula_id": formula_id,
            "tier_level": "bronze",
            "updated_coefficients": {},
            "promotion_flag": False,
        }

    def _fit_linear(self, samples: List[Dict]) -> tuple:
        """Fit y = scale*x + bias using numpy least squares."""
        try:
            import numpy as np
            X = np.array([[s["predicted"], 1.0] for s in samples])
            y = np.array([s["actual"] for s in samples])
            result, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
            scale, bias = float(result[0]), float(result[1])
            preds = X @ result
            mae = float(np.mean(np.abs(preds - y)) / (np.mean(np.abs(y)) + 1e-9))
            return {"scale": round(scale, 6), "bias": round(bias, 4)}, round(mae, 5)
        except ImportError:
            # Fallback: simple mean ratio
            pairs = [(s["predicted"], s["actual"]) for s in samples if s["predicted"] != 0]
            ratios = [a / p for p, a in pairs]
            scale = sum(ratios) / len(ratios) if ratios else 1.0
            mae = sum(abs(a - p * scale) for p, a in pairs) / len(pairs) / (sum(a for _, a in pairs) / len(pairs) + 1e-9) if pairs else 0.0
            return {"scale": round(scale, 6), "bias": 0.0}, round(mae, 5)

    def _compute_tier(self, formula: Dict) -> tuple:
        n_exec = formula["executions"]
        current_tier = formula["tier"]
        tier_order = ["bronze", "silver", "gold", "platinum"]

        new_tier = "bronze"
        for threshold, tier in _TIER_RULES:
            if n_exec >= threshold:
                new_tier = tier

        promoted = tier_order.index(new_tier) > tier_order.index(current_tier)
        return new_tier, promoted
