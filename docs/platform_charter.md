# Cerebrum Platform Charter

**Status:** Active (2026-06-10)  
**Runtime:** [The Fork](https://github.com/bopoadz-del/The_Fork)  
**Store:** Cerebrum-Blocks (this repo)

---

## Vision

Cerebrum is a **block platform** with two products:

| Product | Role |
|---------|------|
| **Virgin Fork** | Stripped runtime template — generic blocks + container host, no domain baked in |
| **Cerebrum-Blocks** | Block Store — discover, publish, and install domain kits onto any Fork instance |

A fresh Fork clone boots as **Virgin Fork** with two outcomes:

1. **~17 plug-and-play generic blocks** — document, AI, search, orchestration primitives (see [generic_blocks.md](./generic_blocks.md))
2. **`DomainContainer` host** — ready to receive kits from the CB store (`POST /store/containers/{id}/install`)

Domain intelligence (construction, legal, medical, …) ships as **kits**, not as mandatory platform code.

---

## Architecture

```
The Fork (virgin boot)
  ├── app/containers/base.py          DomainContainer host
  ├── app/blocks/                     17 generic blocks (default registry)
  └── data/domain_kit_registry.json   ← written by store install

Cerebrum-Blocks (store)
  ├── block_store/kits/{id}/bundle/   Published kit artifacts
  ├── GET  /store/containers          Discovery
  └── POST /store/containers/{id}/install  Copy + register on target
```

### Boot modes

| Env | Behavior |
|-----|----------|
| *(default)* `CEREBRUM_VIRGIN=true` | Generic 17 blocks only; no construction container |
| `CEREBRUM_DOMAIN_KITS=construction` | Enable construction kit blocks + container |
| `CEREBRUM_VIRGIN=false` | Legacy full platform (drives, MCP, sandbox, …) — production Fork |
| Store install | Writes artifacts + `domain_kit_registry.json` on target |

**Production Fork** (Masterise, adapters, live data): set `CEREBRUM_VIRGIN=false` and `CEREBRUM_DOMAIN_KITS=construction`.

---

## Non-negotiables

| Rule | Rationale |
|------|-----------|
| **Keep Fork `chat.py` v3** | RAG, local LLM, TypedBlock, secure prompt loading — CB chat is not a merge target |
| **Do not split the monolith** | `ConstructionContainer` stays one file until a failing test forces a split |
| **Do not swap CB chat into Fork** | Massive regression |
| **Fork = runtime, CB = store** | No wholesale Fork → CB migration |

### Layering (correct)

1. **`ChatBlock`** — mechanics only; caller/container supplies prompts
2. **`DomainContainer.chat()`** — domain policy (`system_prompt_file`, `use_rag`)
3. **Knowledge modules** — PRC rules for domain blocks (`construction_v2`), not generic chat defaults

---

## Construction kit (reference domain)

First published kit. Source of truth: Fork `main`.

| Item | Path |
|------|------|
| Bundle (source of truth) | `block_store/kits/construction/bundle/` |
| Container (after install) | `app/containers/construction.py` (v3.1, monolith) |
| Manifest | `block_store/kits/construction/manifest.json` |
| Publish | `python scripts/publish_construction_kit.py --fork-root <Fork>` |
| Install | `POST /store/containers/construction/install` |

Virgin CB ships **no** construction code under `app/` — only the kit bundle in `block_store/kits/construction/`. Install copies thirty-two artifacts into the consumer `app/` tree (container monolith, 15 domain blocks, reasoning/formula support modules, prompts, and data) and registers the container plus 18 kit blocks in `data/domain_kit_registry.json`; generic `pdf`/`ocr`/`image` remain platform blocks.

---

## Implementation checklist

- [x] `DomainContainer` host (`app/containers/base.py`)
- [x] Virgin boot — construction gated from default registry
- [x] Store install registers kit on target
- [x] Generic blocks documented
- [x] Platform charter (this file)
- [x] Fork `audit.md` strip checklist
- [ ] CI: Fork tag → republish construction bundle
- [ ] Store UI: browse kits, install button

---

## Related docs

- [generic_blocks.md](./generic_blocks.md) — the 17 virgin blocks
- [container_migration_manifest.md](./container_migration_manifest.md) — construction monolith map
- `The_Fork/audit.md` — runtime audit + strip checklist

---

*Fork = runtime. Cerebrum-Blocks = store. Virgin by default; domain via kits.*
