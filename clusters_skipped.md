# Cluster clone candidates — skipped (with reasons)

Worker: codex/agent-wave2-clusters-4de0929a (16 CLUSTER candidates from
docs/survey/store_survey_report.txt). Blocks actually ported are in
block_registry/; this file records the candidates judged not portable.

## insurance cluster (6 of 6 skipped — already registered in the Store)

All six insurance-cluster candidates are the Store's own blocks; the survey's
own recommendation for each is `None` and each is already present and signed
in `block_registry/` (verified with Test-Path before porting). There is no
donor code to clone — cloning them would mean copying the Store onto itself.

- `insurance` — already registered (`block_registry/insurance`). Thin routing
  DomainContainer by design (survey: "Recommendation None").
- `insurance_v2` — already registered (`block_registry/insurance_v2`). The
  survey verified it as real; byte-identical to <private-repo>' vendored copy.
- `agency_hierarchy` — already registered (`block_registry/agency_hierarchy`).
- `bordereaux_ingest` — already registered (`block_registry/bordereaux_ingest`).
  Honest simulated-feed parser; no live-carrier donor exists anywhere.
- `incentive_targeting` — already registered (`block_registry/incentive_targeting`).
- `distribution_analytics` — already registered (`block_registry/distribution_analytics`).

## finance cluster (1 of 3 skipped — already ported in an earlier wave)

- `finance_planning` — already ported on the base branch in wave-2 batch 7
  (commit 13421c8a, `wave-2 batch 7 (clone): finance_planning ported from
  <private-repo> planning/service.py (immutable locked budgets,
  approval-gated lock, allocation remainder routing)`).
  `block_registry/finance_planning` exists and is signed. Not re-cloned.

Note: the third finance candidate ("approval-gated governance workflow") was
split across two existing/ported blocks: `governance_gate` (wave-2 batch 1
ported <private-repo> governance/service.py `require_approved_action` +
approval-request lifecycle) already exists; the unported remainder
(AiUseCase risk-tier register + ModelGovernance validation records) is cloned
in this package as `model_governance`.

## core-infra cluster (2 of 2 skipped)

- `universal_kernel wave1 trust-spine kits` — already exist in
  `block_store/kits/universal_kernel/wave1/` with all six code.py files
  hash-verified against their kernel_manifest.json digests. The survey's
  recommendation is explicit: do not re-extract ("Point <private-repo>'s
  Wave-1 trust-spine mission at this existing, tested, hash-verified kit
  set rather than commissioning new extraction work"). Nothing to clone.
- `isolation.py` (<private-repo> backend/app/cerebrum_product_kernel/isolation.py)
  — survey recommendation: "No action required". It is real, battle-tested
  RLIMIT_AS fork-child address-space budgeting, but it is POSIX-only
  (`os.name != "posix"` → isolation unavailable, so on this Windows build
  every call would degrade to in-process fallback), and the survey notes it
  answers a different question than the Store's scope_guard kit. A Store
  block exposing it would need an invented refusal/API surface the donor
  does not have; per the clone rules (never invent, honest stubs stay
  honest) it is left in the donor rather than faked as a Store block.

## reasoning-orchestration cluster (1 of 1 ported, id renamed)

- `validation_pipeline` (The_Fork app/blocks/validation_pipeline.py) — PORTED,
  but registered as `pint_validation`, not `validation_pipeline`: the Store's
  defs already alias `validation_pipeline` → (`app.blocks.validation`,
  `ValidationBlock`) (commit a5d56d2e "validation_pipeline def points at the
  canonical app.blocks.validation module"), and this worker is barred from
  editing app/blocks/__init__.py. Registering the same id would make the
  census flag a class-name mismatch, so the clone uses the id
  `pint_validation` with the donor class renamed `ValidationPipelineBlock` →
  `PintValidationBlock`. The donor's companion data file is carried at
  `config/empirical_ranges.json`.

## Ported in this package (8 blocks)

| id | donor | provenance |
|----|-------|------------|
| retail_connectors | <private-product> backend/app/retailops/integrations/base.py + connectors/*.py | honest-stub (4 mock-functional connectors inside) |
| pint_validation | The_Fork app/blocks/validation_pipeline.py + config/empirical_ranges.json | real |
| microsoft_365 | Cerebrum backend/app/integrations/microsoft_365.py | real |
| model_governance | <private-repo> backend/app/governance/service.py | real |
| finance_reconciliation_workflow | <private-repo> backend/app/reconciliation/service.py | real |
| mep_zoning | <private-repo> app/agents/zoning.py (+ vendored kit ifc_loader.py zone_key) | real |
| mep_review_ledger | <private-repo> app/review.py + review_package.py + monitors/base.py | real |
| piping_digital_thread | <private-repo> src/<private-repo>/ (package core + exporters) | real |
