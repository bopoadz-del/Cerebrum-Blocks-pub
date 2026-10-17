#!/bin/sh
# Console Floor pack — boot order contract:
#   python -m alembic upgrade head BEFORE serving.
#   A migration failure refuses boot: uvicorn is never started.
# Products that ship no migrations (no alembic.ini) have no schema to fall
# behind: the floor logs that fact and proceeds. The refusal is absolute
# whenever migrations exist.
set -e
cd /app

if [ -f alembic.ini ]; then
  echo "[pack:console_floor] applying migrations before serving (alembic upgrade head)"
  python3 -m alembic upgrade head
  echo "[pack:console_floor] migrations applied"
else
  echo "[pack:console_floor] no alembic.ini in this product — no migrations to apply"
fi

echo "[pack:console_floor] starting uvicorn on :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
