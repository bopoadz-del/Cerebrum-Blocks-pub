# Generic Blocks (Virgin Fork)

Virgin Fork loads these **17 blocks** at every boot. They are domain-agnostic primitives — no construction prompts, no PRC rules, no kit-specific logic.

Registry source: `app/blocks/__init__.py` → `_GENERIC_BLOCK_SPECS`.

---

## Document extraction (4)

| Block | Purpose |
|-------|---------|
| `pdf` | PDF text and table extraction |
| `ocr` | OCR for scanned documents and drawings |
| `image` | Image description and vision analysis |
| `document_engine` | Unified document ingestion pipeline |

## AI / language (5)

| Block | Purpose |
|-------|---------|
| `chat` | LLM mechanics — providers, RAG, local model, streaming (**no domain default prompt**) |
| `translate` | Text translation |
| `voice` | Speech-to-text / text-to-speech |
| `web` | Web page fetch and extraction |
| `search` | Web / corpus search |

## Compute & reasoning (1)

| Block | Purpose |
|-------|---------|
| `code` | Code execution and analysis |

## Search & memory (3)

| Block | Purpose |
|-------|---------|
| `vector_search` | Embedding-based similarity search |
| `zvec` | Lightweight vector operations |
| `cache_manager` | Result caching across block calls |

## Platform glue (4)

| Block | Purpose |
|-------|---------|
| `file_hasher` | Content-addressed cache keys |
| `orchestrator` | Multi-block chain execution |
| `validation_pipeline` | Numeric / structured output validation |
| `async_processor` | Background task dispatch |

---

## Not in virgin boot (extended or kit)

| Category | How to enable |
|----------|---------------|
| Drives (`local_drive`, `google_drive`, …) | `CEREBRUM_VIRGIN=false` |
| MCP (`mcp_adapter`, `mcp_consumer`) | `CEREBRUM_VIRGIN=false` |
| Construction domain | `CEREBRUM_DOMAIN_KITS=construction` or store install |
| `construction_v2`, `boq_processor`, … | Bundled with construction kit |

---

## Store install → target registration

When a kit installs onto a Fork instance:

1. Artifacts copy from `block_store/kits/{id}/bundle/` → target `app/`
2. `data/domain_kit_registry.json` records `container_class` + block list
3. Next boot: `domain_kit_loader` merges kit blocks into `BLOCK_REGISTRY`

Example after construction install:

```json
{
  "kits": {
    "construction": {
      "container_class": "app.containers.construction.ConstructionContainer",
      "blocks": ["boq_processor", "spec_analyzer", "..."],
      "version": "3.1"
    }
  }
}
```

---

## Chat block policy

Fork `chat.py` v3 is the production implementation. Generic chat must not auto-inject domain prompts. Domain containers call `chat()` with `system_prompt_file` set — see `DomainContainer.chat()` in `app/containers/base.py`.

---

*See [platform_charter.md](./platform_charter.md) for the full platform model.*
