FROM python:3.11-slim

WORKDIR /app

# Kernel + neutral pack + platform app (no full store checkout needed).
COPY app/__init__.py ./app/__init__.py
COPY app/reasoning_kernel ./app/reasoning_kernel
COPY domain_packs/equipment_maintenance ./domain_packs/equipment_maintenance
COPY neutral_platform/__init__.py ./neutral_platform/__init__.py
COPY neutral_platform/neutral_app ./neutral_platform/neutral_app
COPY neutral_platform/requirements.txt ./neutral_platform/requirements.txt

RUN pip install --no-cache-dir -r neutral_platform/requirements.txt

EXPOSE 8000

ENV NEUTRAL_DB_URL=sqlite:////app/neutral_platform.db
# NEUTRAL_AUTH_SECRET has no default: pass it at run time (docker run -e ...).

CMD ["uvicorn", "neutral_platform.neutral_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
