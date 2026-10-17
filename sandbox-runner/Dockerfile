FROM python:3.11-slim

# Build deps for the few stdlib accelerators; nothing pip-compiled at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Run as nobody so any process escape lands as an unprivileged uid.
RUN useradd --system --uid 999 --shell /usr/sbin/nologin sandbox \
    && mkdir -p /scratch && chown sandbox:sandbox /scratch
USER sandbox

# Copy the sandbox runner service and the block registry/adapters it needs to
# execute arbitrary blocks out-of-process.
COPY --chown=sandbox:sandbox sandbox-runner/server.py .
COPY --chown=sandbox:sandbox block_registry ./block_registry
COPY --chown=sandbox:sandbox app ./app

# PORT is set by the orchestrator (Render injects 10000 by default;
# docker-compose / local dev defaults to 8001). $PORT respected here so
# the same image works in both environments.
ENV PORT=8001
ENV BLOCK_REGISTRY_ROOT=/app/block_registry
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f "http://localhost:${PORT}/health" || exit 1

# Run with no env passthrough so secrets from the parent env don't leak.
# Operators should run with: docker run --read-only --tmpfs /scratch \
#   --network=none-or-restricted --cap-drop=ALL --user=999:999 ...
# sh -c form so $PORT expands; uvicorn doesn't expand env vars in its argv.
CMD ["sh", "-c", "exec python -m uvicorn server:app --host 0.0.0.0 --port ${PORT} --no-access-log"]
