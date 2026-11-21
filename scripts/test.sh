#!/usr/bin/env bash
# ==============================================================================
# Script to run test suite locally or report container execution
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

if [ -f ".venv/bin/pytest" ]; then
    echo "[*] Running pytest using local virtual environment..."
    .venv/bin/pytest -v "$@"
elif command -v docker &> /dev/null && docker ps --format '{{.Names}}' | grep -q "ehr-backend"; then
    echo "[*] Running pytest inside active ehr-backend Docker container..."
    docker compose exec backend pytest -v "$@"
elif command -v docker &> /dev/null; then
    echo "[*] Running pytest inside ephemeral ehr-backend Docker container..."
    docker compose run --rm backend pytest -v "$@"
else
    echo "[*] Running pytest with system python..."
    pytest -v "$@"
fi
