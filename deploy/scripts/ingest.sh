#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEPLOY_ROOT="${SCRIPT_DIR%/scripts}"
APP_DIR="$DEPLOY_ROOT/app"

export DOCUMENTS_PATH="${DOCUMENTS_PATH:-$DEPLOY_ROOT/data/markdown}"
export VECTORSTORE_PATH="${VECTORSTORE_PATH:-$DEPLOY_ROOT/data/vectorstore}"
export LOG_PATH="${LOG_PATH:-$DEPLOY_ROOT/logs}"
export PYTHONPATH="$APP_DIR:${PYTHONPATH:-}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://localhost:11435}"

mkdir -p "$DOCUMENTS_PATH" "$VECTORSTORE_PATH" "$LOG_PATH"

cd "$DEPLOY_ROOT/.."
uv run --project "$APP_DIR" python -m samanta_rag.ingest "$@"
