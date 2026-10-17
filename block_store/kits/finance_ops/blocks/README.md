# FinanceOps Store Kit

`finance_ops` is the corporate Finance transformation and FP&A kit. It is separate from the existing `finance` investment/document-analysis kit.

## Foundation blocks

- `finance_canonical_model` — governed dimensions, fact types, normalization, and validation
- `finance_import` — row normalization for GL, CRM, HCM, budget, forecast, and project cost
- `finance_data_quality` — required fields, duplicates, period/currency, orphan, and journal controls
- `finance_reconciliation` — Decimal-safe grouped reconciliation and exception evidence
- `finance_coa_governance` — hierarchy, effective-dated mapping, impact, and resolution controls
- `finance_saas_metrics` — MRR, ARR, ACV, TCV, NRR, GRR, renewals, and ARR bridges

## Reused Store capabilities

The kit also references `finance_v2` for financial-document analysis and `formula_executor_v2` for controlled analyst experiments. Approved accounting calculations remain deterministic and versioned; generated formulas are advisory until human-approved.

## Boundaries

- No direct ERP/EPM vendor connector is claimed in v1. Rows arrive from upstream CSV/XLSX/API connector blocks.
- No cross-currency aggregation is performed without explicit governed FX inputs.
- No statutory consolidation or autonomous journal posting.
- Outputs compute, validate, explain, and produce evidence. A human remains the decision authority.
