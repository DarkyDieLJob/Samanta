# Samanta RAG App

Código fuente del agente conversacional RAG desplegado en el VPS.

## Estructura

- `samanta_rag/`: Paquete Python con la lógica de ingestión, configuración y aplicación web.
- `pyproject.toml`: Dependencias del proyecto gestionadas con `uv`.
- `Dockerfile`: Imagen base de la aplicación.

## Comandos útiles

```bash
# Instalar dependencias en entorno local (requiere uv)
uv sync

# Ejecutar ingesta manual
uv run python -m samanta_rag.ingest

# Ejecutar servidor local (FastAPI + Gradio)
uv run python -m samanta_rag.main
```
