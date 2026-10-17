# Console Floor pack — production Dockerfile
# Pin date: 2026-09-20 (python:3.12-slim official image, digest-pinned).
FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PYTHONPATH=/app

# Storage lives on a mounted disk; a product may override STORAGE_PATH.
ENV STORAGE_PATH=/app/data
RUN mkdir -p /app/data

# A red suite must not produce a deployable image: the pack's release gate
# runs the contract + console tests inside the build.
RUN python3 block_store/packs/console_floor/scripts/release_gate.py

EXPOSE 8000

# /health and /ready must both answer; the boot order is alembic-first and
# a migration failure refuses boot (entrypoint exits, uvicorn never starts).
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

ENTRYPOINT ["sh", "/app/block_store/packs/console_floor/scripts/entrypoint.sh"]
