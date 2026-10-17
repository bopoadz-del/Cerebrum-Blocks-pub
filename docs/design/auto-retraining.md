# Design: Auto-retraining pipeline + drift detection

**Status:** MLflow tracker scaffolding shipped (`app/core/mlflow_tracker.py`,
no-op when MLFLOW_TRACKING_URI is unset). Drift detection + retraining
loop are not implemented — this doc scopes them.

## Why

The architecture promises a self-improving system: the **Learning
Engine** records corrections, retrains coefficients, and promotes
formulas through credibility tiers. Today (`app/blocks/learning_engine.py`,
`app/core/credibility.py`):

- Corrections are recorded.
- Coefficients are re-tuned online (running average).
- Tier promotion runs through `CredibilityScorer`.
- **Nothing detects drift**: a formula's accuracy can degrade silently
  if the underlying RSMeans data shifts, the project mix changes, or a
  bug regresses extraction.
- **Nothing retrains**: corrections accumulate, but the system never
  decides "rebuild model X from the last 90 days".

## Goals

- Detect when a formula's rolling accuracy drops below its tier
  threshold for ≥ N consecutive corrections.
- Auto-demote (CredibilityScorer already supports this — it just isn't
  triggered).
- Optionally retrain: queue a job that uses the last K corrections to
  refit the formula's coefficients (or, for ML-backed components,
  retrain a small regression).
- Log every run + every drift event to MLflow so the team has a record.

## Approach

### Phase 1: drift detection (1 day)

In `learning_engine._record_correction`:

```python
recent_n = 20
window = self._recent_predictions(formula_id, n=recent_n)
accuracy_now = 1 - mean_absolute_percentage_error(window)

# Compare to the accuracy at the last tier-promotion point.
baseline = record.accuracy_at_promotion
delta = baseline - accuracy_now

if accuracy_now < tier_threshold(record.tier) and len(window) >= recent_n:
    record.tier = scorer.score(accuracy_now, len(window))   # auto-demote
    self._emit_drift_event(formula_id, baseline, accuracy_now)

if record.tier in (Tier.UNVERIFIED, Tier.EXPERIMENTAL):
    self._enqueue_retrain(formula_id)
```

- Add `accuracy_at_promotion` to `CredibilityRecord` (current state file
  doesn't carry it; migration: default to `accuracy` for existing rows).
- Drift events: structured JSON written to `learning_state.json` under
  `drift_events: []`. Also log to MLflow as a metric (`drift_delta`).

### Phase 2: retrain trigger (2-3 days)

A separate Celery worker (we already have `cerebrum-worker-fast` and
`-slow` on Render):

```python
@celery.task(name="learning.retrain")
def retrain(formula_id: str):
    with mlflow_tracker.start_run(f"retrain-{formula_id}"):
        history = load_corrections(formula_id, limit=500)
        if len(history) < 30:
            return {"skipped": "insufficient data"}

        coeffs = fit_coefficients(history)        # least squares for now
        validate_against_holdout(coeffs, history)
        if better_than_current(coeffs):
            persist(formula_id, coeffs)
            mlflow_tracker.log_metrics({"new_accuracy": ...})
            return {"updated": True, "coefficients": coeffs}
        return {"updated": False, "reason": "no improvement"}
```

- Trigger from `_enqueue_retrain` via Celery task.
- Use Celery beat to also run a nightly sweep of all formulas with
  `EXPERIMENTAL` or `UNVERIFIED` tier — gives them a chance to be
  retrained even without explicit drift.

### Phase 3: model versioning (1-2 days)

Once retrains run, version every coefficient set:

- Write each coefficient version to MLflow as a model artifact.
- `learning_state.json` records `current_version` per formula.
- Rollback: `POST /v1/learning/rollback {formula_id, version}` restores
  the older coefficient set.

### Phase 4: dashboards (1 day)

Grafana dashboard sources from Prometheus + MLflow:

- Per-formula accuracy line chart (Prometheus)
- Per-formula tier history (Prometheus gauge)
- Drift events / retrain runs (MLflow → Grafana panel)
- Top 10 formulas by correction volume

## Concrete next steps

1. **Drift detection** in `learning_engine._record_correction` — 1 day,
   no infra changes. Ships ~80% of the perceived value (auto-demotion
   alerts the team without any retraining loop).
2. **Retrain task** — wire to existing Celery worker. 2-3 days.
3. **Model versioning** — 1-2 days.
4. **Grafana dashboard** — 1 day.

Total: ~6 days of focused work spread across 1-2 sprints. Phase 1 is
the highest-leverage; phases 2-4 are additive and can ship
incrementally.

## Open questions

- **How do we know a correction is right?** Today, `_record_correction`
  trusts the user submitting it. If the user is wrong, drift detection
  will demote a perfectly good formula. Fix: tier of the SUBMITTER
  also weights the correction. Admin corrections count 1.0; user
  corrections count 0.3; if multiple users agree, weight goes up.
- **Do we ever auto-promote?** Yes, the scorer already does — but
  only if accuracy is high AND sample size ≥ 100. Anything else needs
  human review (tier-promotion request goes to a queue).
- **What's the retrain cadence?** Nightly batch is the default; ad-hoc
  trigger when drift is detected.

## Until this lands

- The system records corrections but does not act on them. The
  architecture's "self-improving" claim is aspirational; the engine is
  passive.
- MLflow tracker is no-op unless `MLFLOW_TRACKING_URI` is set. To
  activate: set the env var to `file:./mlruns` for local, or to a
  hosted MLflow URL in prod.
