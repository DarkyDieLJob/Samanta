#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEPLOY_ROOT="${SCRIPT_DIR%/scripts}"
APP_DIR="$DEPLOY_ROOT/app"

OLLAMA_HOST=${OLLAMA_HOST:-http://ollama:11434}
CHAT_MODEL=${MODEL_NAME:-qwen3:8b}
EMBED_MODEL=${EMBEDDING_MODEL_NAME:-nomic-embed-text}

echo "📥 Descargando modelo de chat: $CHAT_MODEL"
curl -sS -X POST "$OLLAMA_HOST/api/pull" -d "{\"name\": \"$CHAT_MODEL\"}" || {
  echo "❌ Error descargando modelo de chat" >&2
  exit 1
}

echo "📥 Descargando modelo de embeddings: $EMBED_MODEL"
curl -sS -X POST "$OLLAMA_HOST/api/pull" -d "{\"name\": \"$EMBED_MODEL\"}" || {
  echo "❌ Error descargando modelo de embeddings" >&2
  exit 1
}
