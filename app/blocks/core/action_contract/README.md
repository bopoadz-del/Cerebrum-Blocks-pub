# Action Contract Runtime

Generic, domain-neutral runtime for registering, discovering, and executing
*actions* (deliverable/analysis operations) exposed by domain kits.

## Modules

- `models` — Pydantic v2 models for `ActionContext`, `ActionSpec`, `ActionOutcome`,
  `ActionResult`, `ActionStatus`, etc.
- `runtime` — `execute_action()`, the single entry point that enforces trust scope,
  validates inputs/outputs, runs async handlers, and returns `ActionResult`.
- `registry` — `ActionRegistry` for discovery and exact-id resolution of `ActionSpec`
  objects from domain packages.
- `schema_validation` — minimal JSON-Schema validator for action input/output
  declarations.
- `audit` — minimal structured audit-record helper.
- `config` — env-driven, product-neutral kernel configuration.

## Usage

```python
from app.blocks.core.action_contract import ActionRegistry, execute_action, ActionContext

registry = ActionRegistry()
registry.discover(package="app.blocks.domains")

spec = registry.resolve("analytics.summarize")
context = ActionContext(
    user_id="u-1",
    tenant_id="t-1",
    organisation_id="org-1",
    project_id="p-1",
    permissions=["read"],
    allowed_domains=["analytics"],
)
result = await execute_action(spec, context, {"query": "..."})
```

## Design principles

- **Trust scope is never sourced from model/caller arguments.** Reserved context
  keys (`tenant_id`, `permissions`, `domain`, etc.) are stripped from action args.
- **Exact-id resolution.** The registry never silently falls back to another action.
- **Deterministic serialization.** Audit records and API responses are byte-stable
  for a given logical value.
- **Product-neutral.** No brand, trade, or vertical-specific labels.
