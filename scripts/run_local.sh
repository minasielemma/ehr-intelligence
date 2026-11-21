#!/usr/bin/env bash
# ==============================================================================
# Script to run FastAPI backend locally using virtualenv
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

if [ ! -d ".venv" ]; then
    echo "[!] Virtual environment (.venv) not found. Creating..."
    python3 -m venv .venv
    echo "[*] Upgrading pip and installing requirements..."
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
fi

echo "[*] Activating virtual environment..."
source .venv/bin/activate

# Ensure local data directory exists
mkdir -p data/storage data/input data/processed

export DATABASE_PATH="${PROJECT_ROOT}/data/storage/ehr.db"
export VECTOR_DB_HOST="${VECTOR_DB_HOST:-localhost}"
export VECTOR_DB_PORT="${VECTOR_DB_PORT:-8001}"

echo "[*] Starting Uvicorn development server on port 8000..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
