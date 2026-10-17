# Validation block naming — CB vs Fork

| Aspect | Cerebrum-Blocks | The_Fork |
|--------|-----------------|----------|
| Virgin boot registry id | `validation_pipeline` | `validation_pipeline` |
| Extended / store registry id | `validation` | _(not registered)_ |
| Implementation module | `app/blocks/validation.py` | `app/blocks/validation_pipeline.py` |
| Class | `ValidationBlock` / `ValidationPipelineBlock` (shim) | `ValidationPipelineBlock` |
| Primary use | Block store certification + item pipeline | Agent numeric guard (Pint units + `config/empirical_ranges.json`) |

## CB shim

`ValidationPipelineBlock` in `app/blocks/validation_pipeline.py` subclasses
`ValidationBlock` and sets `name = "validation_pipeline"` so virgin boot and
Fork agent configs resolve the expected id.

Call via execute envelope or `process({"action": "validate_pipeline", "item": ...})`.

## Fork-only features (not ported)

Fork's standalone `ValidationPipelineBlock` adds Pint dimensional analysis and
file-backed empirical ranges. CB's `validate_pipeline()` uses construction-agnostic
item shape checks and optional `historical_benchmark` dep wiring. Kit agents that
need Fork's Pint checker should install the construction kit bundle or call Fork's
block directly.
