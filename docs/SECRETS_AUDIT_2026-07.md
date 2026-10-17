# Secrets Audit Report — 2026-07

**Generated:** 2026-07-19T08:05:06.213768Z

**Scope:** Read-only scan of full git history across all branches for both repositories.
**Method:** `git log --all -p` parsed for known API-key patterns and high-entropy strings near `KEY/SECRET/TOKEN` keywords.
**Important:** No keys were tested against live services. Format validity is a syntactic check only.
**Action required:** Rotate any live credentials in their respective provider dashboards.

## Repositories scanned

| Repository | HEAD SHA | HEAD branch |
|------------|----------|-------------|
| `bopoadz-del/Cerebrum-Blocks` | `0cf1c505a9a6ed4546a0ef78b2bf95d6d41eb3cd` | `chore/repo-hygiene` |
| `bopoadz-del/<private-repo>` | `035d1754d911750e1754787e7521e23d975c7806` | `master` |

## Summary

| Repository | Findings |
|------------|----------|
| `bopoadz-del/Cerebrum-Blocks` | 10 |
| `bopoadz-del/<private-repo>` | 1 |

| Key type | Count |
|----------|-------|
| Render API key (rnd_...) | 6 |
| DeepSeek API key (sk-...) | 3 |
| OpenAI API key (sk-...) | 1 |
| Generic high-entropy hex string | 1 |

## Findings

### 1. `.render/api-key` — Render API key (rnd_...)

- **Repository:** `bopoadz-del/Cerebrum-Blocks`
- **Redacted value:** `<KEY>`
- **Format valid:** Yes (valid format)
- **Commit SHAs:** 2cc78b24fc27a5c16f161a2173dafd4a673a97bc, 40f39a61f32f91df237abd5e181c4120cf8d6f1d, 8e8726276f3a8f0049af92cbe7c4411ff53cf058, 900cfdc21875f40fd9d411ba86ba9181bec8c899
- **Context:** `<KEY>`

### 2. `TODO.md` — Render API key (rnd_...)

- **Repository:** `bopoadz-del/Cerebrum-Blocks`
- **Redacted value:** `<KEY>`
- **Format valid:** Yes (valid format)
- **Commit SHAs:** 28eeba0c86206ac1d556da97b6bcd45af7c82457, 900cfdc21875f40fd9d411ba86ba9181bec8c899
- **Context:** `RENDER_API_KEY=<KEY>`

### 3. `app/blocks/telegram_bot.py` — Render API key (rnd_...) *(file deleted 2026-08-02; Telegram removed from the platform)*

- **Repository:** `bopoadz-del/Cerebrum-Blocks`
- **Redacted value:** `<KEY>`
- **Format valid:** Yes (valid format)
- **Commit SHAs:** 11a239a3b879ac6f8a3f555b9e2b8d3460ff3085
- **Context:** `f"Render API key: <KEY>\n"`

### 4. `claudebot/bot.py` — Render API key (rnd_...)

- **Repository:** `bopoadz-del/Cerebrum-Blocks`
- **Redacted value:** `<KEY>`
- **Format valid:** Yes (valid format)
- **Commit SHAs:** 24ac1ef9e90055f6aa43583d85dcfca1362a04cb, 289e4730117613df333212a4fe066aaade5f54d8
- **Context:** `Render API key: <KEY>`

### 5. `scripts/render_api.sh` — Render API key (rnd_...)

- **Repository:** `bopoadz-del/Cerebrum-Blocks`
- **Redacted value:** `<KEY>`
- **Format valid:** Yes (valid format)
- **Commit SHAs:** 0b0e245d6cd0ea61c3e7b27437c7fbc101b1e97f, d6a8984e5a212f756c5877b271370069daa40a37
- **Context:** `RENDER_API_KEY="rnd_<KEY>"`

### 6. `TODO.md` — OpenAI API key (sk-...)

- **Repository:** `bopoadz-del/Cerebrum-Blocks`
- **Redacted value:** `<KEY>`
- **Format valid:** Yes (valid standard format)
- **Commit SHAs:** 28eeba0c86206ac1d556da97b6bcd45af7c82457, 900cfdc21875f40fd9d411ba86ba9181bec8c899
- **Context:** `DEEPSEEK_API_KEY=<KEY>`

### 7. `.render/env-vars.txt` — DeepSeek API key (sk-...)

- **Repository:** `bopoadz-del/Cerebrum-Blocks`
- **Redacted value:** `<KEY>`
- **Format valid:** Yes (valid format)
- **Commit SHAs:** 2cc78b24fc27a5c16f161a2173dafd4a673a97bc, 7d3586160922a7289c3be5ebd57ed5238df9c096, 8e8726276f3a8f0049af92cbe7c4411ff53cf058, 900cfdc21875f40fd9d411ba86ba9181bec8c899
- **Context:** `DEEPSEEK_API_KEY=<KEY>`

### 8. `app/blocks/chat.py` — DeepSeek API key (sk-...)

- **Repository:** `bopoadz-del/Cerebrum-Blocks`
- **Redacted value:** `<KEY>`
- **Format valid:** Yes (valid format)
- **Commit SHAs:** 50858f47acc342bbaa005d7d3dee26d4cb9dc367, 81c141bd80fbe13c14530a658f4de913a7ef4732, a71b21e62ab2edeee805e03aaba9dd9e15381fb5, c4966074424d58b90b9fbfc53b23f8547d031086
- **Context:** `api_key = os.getenv("DEEPSEEK_API_KEY") or "<KEY>"`

### 9. `render.yaml` — DeepSeek API key (sk-...)

- **Repository:** `bopoadz-del/Cerebrum-Blocks`
- **Redacted value:** `<KEY>`
- **Format valid:** Yes (valid format)
- **Commit SHAs:** 15f4fc994ed9aa48cc5d205d7a280437a5035fec, 1637855015e7e81ddf5b95a84cb2f9e865551746
- **Context:** `value: <KEY>`

### 10. `app/blocks/chat.py` — Generic high-entropy hex string

- **Repository:** `bopoadz-del/Cerebrum-Blocks`
- **Redacted value:** `<KEY>`
- **Format valid:** Yes (hex, high entropy (3.63))
- **Commit SHAs:** 50858f47acc342bbaa005d7d3dee26d4cb9dc367, 81c141bd80fbe13c14530a658f4de913a7ef4732, a71b21e62ab2edeee805e03aaba9dd9e15381fb5, c4966074424d58b90b9fbfc53b23f8547d031086
- **Context:** `api_key = os.getenv("DEEPSEEK_API_KEY") or "<KEY>"`

### 11. `render_create.py` — Render API key (rnd_...)

- **Repository:** `bopoadz-del/<private-repo>`
- **Redacted value:** `<KEY>`
- **Format valid:** Yes (valid format)
- **Commit SHAs:** 08332f7dc12ef4ffe7315f05228ff8a3ee8ae87b, 4b940a100185ad16a202db454ede15e234433425
- **Context:** `RENDER_API_KEY = os.getenv("RENDER_API_KEY", "<KEY>")`

## Notes & exclusions

- Paths containing `node_modules`, `.venv`, lockfiles, build output, and bundled/minified assets were excluded from generic high-entropy matches to reduce false positives.
- Generic hex/base64 matches are only reported when they appear on a line containing `KEY`, `SECRET`, `TOKEN`, `PASSWORD`, `AUTH`, or `CREDENTIAL`.
- The actual secret values are redacted in this report; only the first and last few characters are shown.
- This audit does not prove keys are active; rotate any credential that may have been live.
