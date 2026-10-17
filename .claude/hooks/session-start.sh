#!/bin/bash
# SessionStart hook for Cerebrum Blocks.
# Installs Python + frontend deps so pytest, tsc, and eslint work in
# Claude Code on the web. Idempotent and non-interactive.
set -euo pipefail

# Only run in Claude Code on the web; locals already have their own setup.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

echo "[session-start] Python: $(python3 --version 2>&1)"
echo "[session-start] Node:   $(node --version 2>&1)  npm: $(npm --version 2>&1)"

# --- System packages required by OCR/PDF blocks (best-effort) ----------
# pytesseract + pdf2image need these. apt may not be available; that's fine.
if command -v apt-get >/dev/null 2>&1; then
    echo "[session-start] Installing system deps (tesseract, poppler)…"
    if [ "$(id -u)" -eq 0 ]; then
        APT="apt-get"
    else
        APT="sudo -n apt-get"
    fi
    $APT update -qq || true
    DEBIAN_FRONTEND=noninteractive $APT install -y --no-install-recommends \
        tesseract-ocr poppler-utils libgl1 libglib2.0-0 >/dev/null 2>&1 \
        || echo "[session-start] WARN: system deps install skipped (no sudo or apt)"
fi

# --- Python deps -------------------------------------------------------
echo "[session-start] Installing Python dependencies…"
# Best-effort pip upgrade — may be a dpkg-managed pip we can't replace.
python3 -m pip install --quiet --upgrade pip 2>/dev/null || \
    echo "[session-start] (pip upgrade skipped, using system pip)"
# --break-system-packages handles PEP 668 environments (Debian/Ubuntu noble).
# --ignore-installed avoids "RECORD file not found" on dpkg-installed packages.
# --break-system-packages handles PEP 668 (Debian/Ubuntu noble).
python3 -m pip install --quiet --break-system-packages --ignore-installed -r requirements.txt 2>/dev/null \
    || python3 -m pip install --quiet --ignore-installed -r requirements.txt

# --- Frontend deps -----------------------------------------------------
if [ -d frontend ] && [ -f frontend/package.json ]; then
    echo "[session-start] Installing frontend npm dependencies…"
    # `npm ci` reads package-lock.json verbatim and never modifies it, so
    # the working tree stays clean across SessionStart runs. Falls back to
    # `npm install` if the lockfile is missing or out of sync.
    (cd frontend && (npm ci --no-audit --no-fund --loglevel=error \
        || npm install --no-audit --no-fund --loglevel=error))
fi

# --- Persist env for the session --------------------------------------
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    {
        echo "export ENV=test"
        echo "export PYTHONPATH=\"${CLAUDE_PROJECT_DIR:-$(pwd)}\""
    } >> "$CLAUDE_ENV_FILE"
fi

echo "[session-start] Done."
