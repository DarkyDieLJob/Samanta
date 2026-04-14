#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEPLOY_ROOT="${SCRIPT_DIR%/scripts}"
APP_DIR="$DEPLOY_ROOT/app"

export DOCUMENTS_PATH="${DOCUMENTS_PATH:-$DEPLOY_ROOT/data/markdown}"
export VECTORSTORE_PATH="${VECTORSTORE_PATH:-$DEPLOY_ROOT/data/vectorstore}"
export LOG_PATH="${LOG_PATH:-$DEPLOY_ROOT/logs}"
export PYTHONPATH="$APP_DIR:${PYTHONPATH:-}"

API_URL=${1:-http://localhost:7860}
if [[ $# -gt 0 ]]; then
  shift
fi

mkdir -p "$DOCUMENTS_PATH" "$VECTORSTORE_PATH" "$LOG_PATH"

cd "$DEPLOY_ROOT/.."
uv run --project "$APP_DIR" python -m samanta_rag.diagnostics --api-url "$API_URL" "$@"
