# Cerebrum Blocks Deployment Configs

Multi-platform deployment configurations for cloud and edge environments.

## 📁 Structure

```
deploy/
├── cloud/              # Docker configs for cloud deployment
│   └── Dockerfile          # Main API container
├── edge/               # Edge/Jetson deployment
│   └── Dockerfile.jetson   # ARM64/CUDA optimized
└── README.md
```

(There is no Celery worker container and no blueprint here — the live
service is dashboard-managed Docker; see ../docs/RUNBOOK.md.)

## 🚀 Quick Deploy

### Render.com (Recommended for Quick Start)

Push to GitHub - Render auto-deploys from main branch.
Services are managed manually on the Render dashboard (no Blueprint).

### Docker (Local/Cloud)

```bash
# Build and run locally
docker-compose up -d

# Or build specific targets
docker build -f deploy/cloud/Dockerfile -t cerebrum:cloud .
docker run -p 8000:8000 -e PORT=8000 cerebrum:cloud
```

### NVIDIA Jetson (Edge)

```bash
# Build for ARM64/CUDA
docker build -f deploy/edge/Dockerfile.jetson -t cerebrum:jetson .

# Run on Jetson
docker run -p 8000:8000 --runtime nvidia cerebrum:jetson
```

## ⚙️ Environment Configs

| File | Environment | Profile |
|------|-------------|---------|
| `config/cloud.yaml` | Render/GCP/Cloud | `cloud_render` |
| `config/edge.yaml` | Jetson/Local | `jetson_orin` |

## 🔑 Required Secrets

Create `.env` file:

```bash
# AI Providers (paste from your vault)
DEEPSEEK_API_KEY=
GROQ_API_KEY=
OPENAI_API_KEY=

# Database
DATABASE_URL=postgresql://...
REDIS_URL=redis://...

# Auth (generate in your vault)
JWT_SECRET=
```

## 🏥 Health Checks

- **API Health**: `GET /v1/health`
- **Dashboard**: Static site health via Render
- **Worker**: Celery worker monitor
