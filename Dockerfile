# ═══════════════════════════════════════════════════════════════════════
# Cerebrum Blocks — Production Dockerfile
# ═══════════════════════════════════════════════════════════════════════

FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system dependencies (single layer to reduce image size)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build tools
    build-essential gcc g++ gfortran pkg-config \
    # PDF / image processing
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender-dev \
    poppler-utils \
    # OCR (critical for capture, ocr, ocr_v2 blocks)
    tesseract-ocr tesseract-ocr-ara libtesseract-dev \
    # Networking / healthchecks
    curl \
    # Cleanup
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Create non-root user with a fixed uid for predictable file ownership
RUN groupadd --system --gid 1000 cerebrum && \
    useradd --system --uid 1000 --gid cerebrum --create-home --shell /bin/bash cerebrum

# Copy application code with non-root ownership
COPY --chown=cerebrum:cerebrum . .

# Persistent data volume — created and owned by cerebrum so the running
# user can write uploads/data without needing root.
RUN mkdir -p /app/data && chown -R cerebrum:cerebrum /app/data && \
    chmod +x /app/entrypoint.sh
VOLUME /app/data

# Healthcheck. /ready, not /health: /health is liveness and always returns
# 200, so it can never mark a container unhealthy. /ready probes the real
# dependencies and returns 503 when the service is up but broken.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/ready || exit 1

USER cerebrum
EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
