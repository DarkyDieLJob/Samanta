#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd)
DEPLOY_ROOT="${SCRIPT_DIR%/scripts}"
ENV_FILE="$DEPLOY_ROOT/.env"
ENV_TEMPLATE="$DEPLOY_ROOT/.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ ! -f "$ENV_TEMPLATE" ]]; then
    echo "❌ No se encontró $ENV_TEMPLATE; crea el archivo antes de continuar." >&2
    exit 1
  fi
  cp "$ENV_TEMPLATE" "$ENV_FILE"
  echo "✅ Archivo .env creado a partir de .env.example"
else
  echo "ℹ️ Archivo .env ya existe, no se modifica."
fi

DATA_DIR="$DEPLOY_ROOT/data"
MARKDOWN_DIR="$DATA_DIR/markdown"
VECTORSTORE_DIR="$DATA_DIR/vectorstore"
LOG_DIR="$DEPLOY_ROOT/logs"

mkdir -p "$MARKDOWN_DIR" "$VECTORSTORE_DIR" "$LOG_DIR"
chmod 755 "$MARKDOWN_DIR" "$VECTORSTORE_DIR" "$LOG_DIR"

echo "📁 Directorios preparados:"
echo "  - $MARKDOWN_DIR"
echo "  - $VECTORSTORE_DIR"
echo "  - $LOG_DIR"

if [[ ! -s "$MARKDOWN_DIR"/001_la_ferreteria.md ]]; then
  cat <<'EOF' >"$MARKDOWN_DIR/README.txt"
Agrega tus archivos Markdown (.md) en este directorio.
Cada archivo se ingiere automáticamente al iniciar el stack.
EOF
  echo "ℹ️ Añadido README de ayuda en $MARKDOWN_DIR"
fi

echo "✅ Preparación completada. Ya puedes ejecutar 'docker compose -f deploy/docker-compose.yml up -d'."
