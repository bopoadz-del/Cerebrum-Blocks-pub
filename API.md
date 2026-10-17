# Cerebrum Blocks API Reference

## 🚀 Quick Start (3-minute chain)

```bash
# Construction AI in one call
curl -X POST https://cerebrum-platform-api.onrender.com/v1/chain \
  -H "Content-Type: application/json" \
  -d '{
    "steps": [
      {"block": "construction", "params": {"action": "extract_measurements"}},
      {"block": "ai_core", "params": {"action": "chat", "prompt": "Calculate total material cost"}}
    ],
    "initial_input": {"url": "your-floorplan.pdf"}
  }'
```

---

## 🏥 Health Check

Liveness — unauthenticated, no I/O, always 200. Use it to answer "is the
process up", nothing more.

```bash
GET /health
GET /v1/health
```

**Response:**
```json
{
  "status": "ok"
}
```

Readiness — unauthenticated, probes real dependencies, returns **503** when
degraded. This is the endpoint platform health checks should target
(`render.yaml` sets `healthCheckPath: /ready`); `/health` can never fail.

```bash
GET /ready
GET /v1/ready
```

**Response (200):**
```json
{
  "status": "ready",
  "checks": {"data_dir": "ok", "block_registry": "ok"}
}
```

**Response (503):**
```json
{
  "status": "degraded",
  "checks": {"data_dir": "fail", "block_registry": "ok"}
}
```

Diagnostics — **requires an API key**. Block counts, the evaluated Kimi
workbench capability, and the readiness checks. The subprocess probe is
cached (`KIMI_PROBE_TTL_SECONDS`, default 300); pass `?refresh=true` to
force a fresh reading.

```bash
GET /v1/system/diagnostics
Authorization: Bearer YOUR_API_KEY
```

---

## ♻️ Exact-id REUSE / present (Factory STEP 0)

Auth required. This is a **registry query**, not a guess: the path segment
is the exact store id (`block_registry/{id}/block.json`). Factory should
call this for STEP 0 inventory instead of inferring whether a block exists.

```bash
GET /v1/registry/blocks/{block_id}
GET /v1/registry/reuse/{block_id}
Authorization: Bearer YOUR_API_KEY
```

**Present:**
```json
{
  "present": true,
  "id": "document_engine",
  "reuse": true,
  "source": "registry",
  "reads": [{"kind": "file", "scope": "input_document"}],
  "writes": [{"kind": "caller", "scope": "output"}],
  "never": [],
  "acceptance": [{"id": "...", "check": "...", "status": "refused"}],
  "manifest": { "...": "full block.json including L2.2 brief-scope fields" }
}
```

**Absent** — always HTTP 200; `present` is the inventory bit:
```json
{
  "present": false,
  "id": "no_such_block",
  "reuse": false
}
```

Unversioned alias: `GET /registry/blocks/{block_id}`.

`block.json` L2.2 brief-scope fields (`reads`, `writes`, `never`,
`acceptance`) are **report-only until the flip**. Lane 2 / the store
audit warn on missing or invalid values; they do not fail-close the
store. `BRIEF_SCOPE_FAIL_CLOSED` stays `False` until an owner-gated PR.
Empty `acceptance` on a measured backfill means the handler has no
fail-loud sentence this store could pin — do not invent one.

---

## 📦 List Blocks

```bash
GET /blocks
```

**Response:**
```json
{
  "blocks": [
    {"name": "pdf", "version": "1.1", "description": "..."},
    {"name": "chat", "version": "1.2", "description": "..."},
    {"name": "construction", "version": "1.0", "description": "..."}
  ],
  "total": 19
}
```

---

## ⚡ Execute Single Block

```bash
POST /execute
```

**Request:**
```json
{
  "block": "chat",
  "input": "Explain quantum computing",
  "params": {"provider": "deepseek"}
}
```

**Response:**
```json
{
  "block": "chat",
  "status": "success",
  "result": {
    "text": "Quantum computing is...",
    "provider": "deepseek",
    "tokens_total": 26
  }
}
```

---

## 🔗 Chain Execution

```bash
POST /chain
```

**Request:**
```json
{
  "steps": [
    {"block": "pdf", "params": {"action": "extract"}},
    {"block": "ocr", "params": {}},
    {"block": "chat", "params": {"prompt": "Summarize"}}
  ],
  "initial_input": {"url": "https://example.com/doc.pdf"}
}
```

**Response:**
```json
{
  "success": true,
  "steps_executed": 3,
  "final_output": "Summary text...",
  "results": [
    {"step": 0, "block": "pdf", "success": true},
    {"step": 1, "block": "ocr", "success": true},
    {"step": 2, "block": "chat", "success": true}
  ]
}
```

---

## 🏗️ Construction API

### Extract Measurements
```bash
POST /execute
{
  "block": "construction",
  "input": {},
  "params": {"action": "extract_measurements"}
}
```

**Response:**
```json
{
  "status": "success",
  "quantities": {
    "concrete_volume_m3": 45.5,
    "steel_weight_kg": 1200,
    "floor_area_m2": 111.5
  },
  "confidence": 0.94
}
```

### QA Inspection
```bash
POST /execute
{
  "block": "construction",
  "input": {},
  "params": {"action": "qa_inspection", "trade": "concrete"}
}
```

### Progress Tracking
```bash
POST /execute
{
  "block": "construction",
  "input": {},
  "params": {"action": "progress_tracking"}
}
```

### BIM Analysis
```bash
POST /execute
{
  "block": "construction",
  "input": {},
  "params": {"action": "bim_analysis"}
}
```

---

## 🔐 Security API

### Create API Key
```bash
POST /execute
{
  "block": "security",
  "input": {},
  "params": {
    "action": "create_key",
    "owner": "my_app",
    "role": "admin"
  }
}
```

### Authenticate
```bash
POST /execute
{
  "block": "security",
  "input": {},
  "params": {
    "action": "auth",
    "api_key": "cb_..."
  }
}
```

### Rate Limit Check
```bash
POST /execute
{
  "block": "security",
  "input": {},
  "params": {
    "action": "check_rate",
    "key": "user_123",
    "limit": 100
  }
}
```

---

## 🤖 AI Core API

### Provider Leaderboard
```bash
POST /execute
{
  "block": "ai_core",
  "input": {},
  "params": {"action": "leaderboard"}
}
```

### Adaptive Route
```bash
POST /execute
{
  "block": "ai_core",
  "input": {},
  "params": {"action": "route", "quality": "fast"}
}
```

### Failover Status
```bash
POST /execute
{
  "block": "ai_core",
  "input": {},
  "params": {"action": "failover_status"}
}
```

---

## 🏪 Store API

### Platform Stats
```bash
POST /execute
{
  "block": "store",
  "input": {},
  "params": {"action": "platform_stats"}
}
```

---

## 🏛️ Architecture

```
Layer 0 → Infrastructure (HAL, Config, Memory, Database)
Layer 1 → Security (Auth, Secrets, Audit, Rate Limiter)
Layer 2 → AI Core (Adaptive Router, Failover, Leaderboard)
Layer 3 → Construction (BIM, PDF, OCR, QA, Progress) ← DIFFERENTIATOR
Layer 4 → Store (Lego Tax marketplace)
Event Bus → Connects all containers (Block 42)
```

**Total: 28+ Blocks**

---

## 📊 Response Codes

| Status | Meaning |
|--------|---------|
| `success` | Block executed successfully |
| `error` | Execution failed (see `result.error`) |
| `pending` | Async operation in progress |

---

**Deployed:** https://cerebrum-platform-api.onrender.com  
**Version:** 2.0.0  
**Status:** ✅ PRODUCTION READY
