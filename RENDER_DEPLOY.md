# 🚀 Deploy Cerebrum Blocks to Render

Complete guide to deploy the Cerebrum Blocks API on Render.

> **Live production truth (2026-08):** the store runs as Render service
> **`cerebrum-blocks`** on the **Docker runtime** (`./Dockerfile` →
> `entrypoint.sh`), managed in the dashboard — NOT via `render.yaml`, which
> describes the suspended `cerebrum-platform-api` python-runtime service the
> steps below were written for. For day-2 operations (health, rollback, key
> rotation, backups) see **[docs/RUNBOOK.md](docs/RUNBOOK.md)**. The manual
> steps below remain valid only for standing up a fresh python-runtime
> instance from scratch.

## Quick Deploy (One-Click)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/bopoadz-del/cerebrum-blocks)

*(Replace with your actual repo URL)*

## Manual Deploy

### Step 1: Create Account
1. Go to [render.com](https://render.com)
2. Sign up with GitHub
3. Connect your repository

### Step 2: Create Web Service
1. Click **"New +"** → **"Web Service"**
2. Connect your GitHub repo
3. Fill in the form:

| Setting | Value |
|---------|-------|
| **Name** | `cerebrum-platform-api` |
| **Environment** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` *(tesseract-ocr auto-installed via `Aptfile`)* |
| **Start Command** | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| **Plan** | Free (or paid for production) |

### Step 3: Add Disk (Optional but Recommended)
For persistent storage:
1. Click **"Disks"** in your service
2. **Name**: `data`
3. **Mount Path**: `/app/data`
4. **Size**: 1 GB (or more)

### Step 4: Set Environment Variables
Go to **Environment** tab and add:

```bash
# Required
PYTHON_VERSION=3.11.0
DATA_DIR=/app/data            # must match the mounted disk path
ENV=production
LOG_LEVEL=INFO
LOG_FORMAT=json
CORS_ORIGINS=https://cerebrum-platform.onrender.com   # SPA origin

# API Keys (master + per-user — generate in your vault, paste into Render env vars)
CEREBRUM_MASTER_KEY=
CEREBRUM_API_KEY_ALICE=
CEREBRUM_API_KEY_BOB=

# Optional - AI providers (chat block falls back to rule-based offline if both missing)
DEEPSEEK_API_KEY=
ANTHROPIC_API_KEY=

# Optional - error tracking
SENTRY_DSN=
```

`scripts/render-rotate.sh` applies the non-secret vars (`CORS_ORIGINS`,
`LOG_LEVEL`, `LOG_FORMAT`, `ENV`, `VITE_API_BASE`) and triggers a redeploy
without touching any `*_KEY`. Use it after env changes you can script.

### Step 5: Deploy
Click **"Create Web Service"**

Wait for build (~2-3 minutes), then visit your URL!

---

## Managing users (small-scale, ≤ ~10 users)

The auth layer reads keys from environment variables. Any env var named
`CEREBRUM_API_KEY_<NAME>` is a valid user key. The auth cache reloads
from env every 60 seconds (`API_KEYS_RELOAD_TTL` to tune), so adding,
rotating, or revoking a user takes effect within a minute — **no
redeploy needed**.

**Add a user:**
1. Generate a key locally: `python -c "import secrets; print('sk-cb-' + secrets.token_hex(16))"`
2. Render dashboard → API service → Environment → add `CEREBRUM_API_KEY_<NAME>` with that value
3. Save (Render does NOT need to redeploy — wait ≤60s)
4. Hand the user the key; they pass it as `Authorization: Bearer <key>`

**Revoke a user:** delete the env var, wait ≤60s.

**Rotate a user's key:** edit the env var to a new value, wait ≤60s — old key stops working, new one starts.

The `CEREBRUM_MASTER_KEY` is the admin key (unlimited rate). The
per-user keys get tier=`standard`, 1000 req/hr.

## Post-Deploy Setup

### 1. Verify Deployment
```bash
curl https://your-service.onrender.com/v1/health
```

### 2. Test a Block
```bash
curl -X POST https://your-service.onrender.com/v1/chat \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hello from Render!"
  }'
```

### 3. API Documentation
Visit: `https://your-service.onrender.com/docs`

---

## SDK Usage with Your Deployed API

```python
from cerebrum import CerebrumClient

client = CerebrumClient(
    api_key="your-key",
    base_url="https://your-service.onrender.com"
)

response = client.chat("Hello!")
print(response.text)
```

```javascript
import { CerebrumClient } from 'cerebrum-blocks';

const client = new CerebrumClient({
  apiKey: 'your-key',
  baseUrl: 'https://your-service.onrender.com'
});

const response = await client.chat('Hello!');
console.log(response.text);
```

---

## Troubleshooting

### Build Fails (tesseract-ocr)
Render auto-installs packages listed in `Aptfile`:
```
tesseract-ocr
```
No `apt-get` needed in build command.

### Port Issues
Render automatically sets `$PORT`. Don't hardcode it!

### Disk Not Persisting
Ensure `DATA_DIR=/app/data` matches your disk mount path.

### Import Errors
```bash
# Check requirements.txt is in root
# Verify app/__init__.py exists
```

---

## Production Checklist

- [ ] Upgrade from Free plan
- [ ] Add custom domain
- [ ] Set up environment variables
- [ ] Add disk for persistence
- [ ] Configure CORS if needed
- [ ] Set up monitoring/health checks
- [ ] Enable auto-deploy on push

---

## Free Tier Limits

| Resource | Limit |
|----------|-------|
| RAM | 512 MB |
| CPU | Shared |
| Disk | 1 GB |
| Sleep | After 15 min idle |
| Bandwidth | 100 GB/month |

Upgrade for production use!
