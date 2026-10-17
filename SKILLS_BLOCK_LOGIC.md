# Skills Block Logic

> **Platform note:** The `skills` block is extended-boot / store-only (`CEREBRUM_VIRGIN=false`).
> Example deliverables below skew construction because the bundled `CEREBRUM_SKILL.md`
> ships with the construction kit. Virgin platform boot does not load this block;
> domain kits may supply their own skill files via `skill_file` config.

## Overview

The `skills` block parses `data/CEREBRUM_SKILL.md` and serves structured hints to the orchestrator so that construction deliverables are produced with the correct tooling, styles, and validation gates.

## Route Logic

```
User Request
    │
    ▼
┌─────────────────────┐
│  smart_orchestrator │ ── keyword routing ──► action_queue
│                     │
│  (wired to skills)  │ ── skill hints ──────► skill_hints
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│  skills             │ ── parses CEREBRUM_SKILL.md sections
│  (knowledge base)   │ ── returns hints/validation/styles
└─────────────────────┘
    │
    ▼
┌─────────────────────┐
│  construction block │ ── produces deliverable (xlsx/pdf/docx/pptx)
│  (orchestrator      │    using skill_hints for styling & validation
│   execution)        │
└─────────────────────┘
```

## Block Interface

### Actions

| Action | Params | Returns |
|--------|--------|---------|
| `hints` | `deliverable` or `workflow` | Relevant hints for the deliverable/workflow |
| `validation` | `deliverable` | Shared + specific validation rules |
| `style` | `deliverable` | Style system for the deliverable type |
| `workflow` | `workflow` | Full pipeline for a domain workflow |
| `list` | — | All deliverables and workflows |
| `full` | `deliverable` | Full skill markdown section |

### Deliverable Types

- `xlsx` — BOQ, cost estimates, financial models
- `pdf` — Technical reports, data sheets, QA reports
- `docx` — Contracts, narratives, meeting minutes
- `pptx` — Presentations, investor pitches
- `webapp` — Dashboards, client portals
- `backend` — APIs, data pipelines
- `image-pdf` — Drone QA/QC reports
- `ifc-xlsx` — BIM quantity takeoffs

### Workflow Types

- `drone_qaqc` — Drone → defect detection → PDF + XLSX
- `bim_boq` — IFC → quantities → XLSX BOQ
- `progress_dashboard` — Site data → FastAPI → React dashboard

## Orchestrator Wiring

`SmartOrchestratorBlock` maps matched actions to deliverable types via `ACTION_DELIVERABLE_MAP`. After routing, it calls:

```python
skills.execute(deliverable, {"action": "hints", "deliverable": deliverable})
skills.execute(deliverable, {"action": "validation", "deliverable": deliverable})
```

Results are injected into the orchestrator response as `skill_hints`, so downstream blocks can access:

- `skill_hints.deliverable` — the deliverable type
- `skill_hints.hints` — tech stack, key rules, use case
- `skill_hints.validation` — pre-flight checklist, per-artifact loop, post-delivery gate

## REST Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/skills/deliverables` | List all deliverables & workflows |
| POST | `/skills/hints` | Get hints for a deliverable/workflow |
| POST | `/skills/validation` | Get validation rules |
| POST | `/skills/style` | Get style system |
| POST | `/skills/workflow` | Get workflow pipeline |

All endpoints also work through the universal `/execute` and `/chain` APIs since `skills` is registered in `BLOCK_REGISTRY`.

## Example Chain

```json
{
  "steps": [
    {"block": "smart_orchestrator", "params": {}, "input_mapping": {"user_message": "input"}},
    {"block": "skills", "params": {"action": "hints"}, "input_mapping": {"action_queue.0": "deliverable"}},
    {"block": "construction", "params": {"action": "extract_quantities"}}
  ],
  "initial_input": "Generate a BOQ from the floor plan"
}
```

## File Dependencies

- `data/CEREBRUM_SKILL.md` — Source of truth for all skill knowledge
- `app/blocks/skills.py` — Block implementation
- `app/blocks/smart_orchestrator.py` — Wired to consume skill hints
- `app/routers/skills.py` — Dedicated REST endpoints
