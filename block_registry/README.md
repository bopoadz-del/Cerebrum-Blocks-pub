# Cerebrum Block Registry

This directory contains the **plug-and-play block registry** for Cerebrum-Blocks.
Each block is self-contained with its own metadata, execution wrapper, and Docker configuration.

## Structure

```
block_registry/
├── Dockerfile.base              # Shared base image for all blocks
├── run.py                       # Universal stdin/stdout wrapper
├── chat/
│   ├── block.json               # Block metadata (inputs, outputs, UI schema)
│   ├── block.py                 # Thin adapter wrapping app.blocks.chat
│   └── Dockerfile               # Per-block Docker image
├── pdf/
│   ├── block.json
│   ├── block.py
│   └── Dockerfile
└── ... (more blocks)
```

## block.json Schema

Each block manifest follows this structure. Inline blocks (`app/blocks/*.py`) use the same contract via `UniversalBlock.ui_schema`:

```json
{
  "id": "chat",
  "name": "Chat",
  "version": "2.0.0",
  "author": "Cerebrum Team",
  "description": "AI chat completions",
  "layer": 2,
  "requires": [],
  "tags": ["ai", "core", "llm", "chat"],
  "inputs": [
    {"name": "input", "type": "string", "required": false, "description": "..."}
  ],
  "outputs": [
    {"name": "text", "type": "markdown", "description": "Response"}
  ],
  "execution": {
    "type": "docker",
    "image": "ghcr.io/cerebrum-blocks/chat:latest"
  },
  "ui_schema": [
    {"name": "input", "widget": "text", "label": "Ask anything..."},
    {"name": "action", "widget": "select", "label": "Action", "options": ["get", "set"]}
  ]
}
```

Python blocks should also define:

```python
ui_schema = {
    "input": {"type": "json", "placeholder": "...", "multiline": True},
    "output": {"type": "json", "fields": [{"name": "result", "type": "json", "label": "Result"}]},
    "params": [
        {"name": "action", "type": "select", "label": "Action", "options": [...], "default": "get"},
        {"name": "max_tokens", "type": "number", "label": "Max tokens", "default": 2048},
    ],
    "quick_actions": [],
}
```

Use `app/core/ui_schema_builder.py` helpers (`action_ui_schema`, `file_ui_schema`, etc.) to stay consistent.

## Running a Block Standalone

### Inline (requires backend environment)

```bash
cd /path/to/cerebrum-blocks/block_registry/chat
python ../run.py < <(echo '{"input": "Hello!"}')
```

### Via Adapter Directly

```bash
cd /path/to/cerebrum-blocks
python -c "
import json
from block_registry.chat.block import run
result = run(input='Hello!')
print(json.dumps(result, indent=2))
"
```

### Docker

```bash
# Build the base image first
docker build -f block_registry/Dockerfile.base -t cerebrum-block-base:latest .

# Build a specific block
docker build -t ghcr.io/cerebrum-blocks/chat:latest block_registry/chat/

# Run it
echo '{"input": "Hello!"}' | docker run -i ghcr.io/cerebrum-blocks/chat:latest
```

## Adding a New Block

1. Create a folder: `block_registry/my_block/`
2. Add `block.json` with metadata
3. Add `block.py` with a `run(**kwargs)` function
4. Add `Dockerfile` (copy from existing block)
5. Test: `python scripts/test_block_registry.py my_block`

## Auto-Generation

To regenerate all block manifests from the existing `app/blocks/` codebase:

```bash
python scripts/generate_block_registry.py
```

This scans the `BLOCK_REGISTRY`, extracts metadata, and writes `block.json` + `block.py` + `Dockerfile` for each block.

## Batch Build

To build all Docker images:

```bash
./scripts/build_all_images.sh
```

To push to a registry:

```bash
./scripts/build_all_images.sh ghcr.io/your-org
```

## Backward Compatibility

The existing FastAPI endpoints (`/v1/execute`, `/chain`, `/blocks`) continue to work exactly as before. Registry blocks are **additive** — they provide a standalone execution path without modifying the original inline blocks.
