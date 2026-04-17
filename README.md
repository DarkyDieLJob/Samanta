# Samanta RAG

Implementación de un asistente conversacional basado en Retrieval Augmented Generation (RAG) para un negocio local, empaquetado con Docker Compose y siguiendo una arquitectura hexagonal.

## Características principales

- Arquitectura hexagonal con capas de dominio, aplicación, infraestructura e interfaces.
- FastAPI para la API HTTP y Gradio para la interfaz web conversacional.
- Ingesta incremental de documentos Markdown en un vector store FAISS.
- Integración con Ollama (modelos `qwen3:8b` y `nomic-embed-text`).
- Consumo de proveedores MCP vía WebSocket con ruteo dinámico por intención, fallback a FAISS y observabilidad (métricas p50/p95/p99 por herramienta).
- Scripts de ayuda para provisión, ingesta y diagnósticos.

## Requisitos

- Docker y Docker Compose
- Git
- Conexión a internet para descargar modelos de Ollama la primera vez

## Preparación del proyecto

```bash
git clone https://github.com/<tu-usuario>/Samanta.git
cd Samanta/deploy
./scripts/provision.sh
```

El script `provision.sh` crea `.env` a partir de `.env.example`, prepara los directorios compartidos (`data/`, `logs/`) y deja un recordatorio en `data/markdown` si todavía no tienes contenido.

Si necesitas personalizar variables (nombre de modelos, preguntas sugeridas, IP allowlist, etc.), edita el nuevo `.env` antes de levantar los servicios.

## Despliegue con Docker Compose

```bash
# Construye imágenes y levanta los servicios en segundo plano
docker compose -f deploy/docker-compose.yml up -d --build

# Verifica el estado
docker compose -f deploy/docker-compose.yml ps

# Opcional: sigue los logs en vivo
docker compose -f deploy/docker-compose.yml logs -f
```

La composición incluye:

1. `ollama`: servidor Ollama expuesto en el puerto 11435 hacia el host.
2. `model-init`: contenedor efímero que descarga los modelos definidos en `.env` y libera al resto de servicios cuando termina.
3. `app`: servicio FastAPI + Gradio (`samanta_rag.main`).
4. `refresher`: proceso de ingesta en modo watch (`samanta_rag.ingest --watch`).

La interfaz web queda disponible en `http://<ip-servidor>:7860`.

## Scripts útiles

- `deploy/scripts/provision.sh`: prepara `.env`, carpetas compartidas y permisos.
- `deploy/scripts/ingest.sh`: ejecuta manualmente la ingesta de documentos.
- `deploy/scripts/diagnostics.sh`: corre el módulo de diagnósticos contra la API indicada.
- `deploy/scripts/pull_models.sh`: permite descargar modelos desde el host si necesitas forzar la operación.

## Estructura de carpetas

```
Samanta/
├── deploy/
│   ├── app/                # Código fuente del proyecto (FastAPI, Gradio, lógica RAG)
│   ├── data/               # Markdown y vectorstore (montados como volúmenes)
│   ├── logs/               # Archivos de log compartidos
│   ├── docker-compose.yml  # Orquestación de servicios
│   └── scripts/            # Scripts auxiliares
├── INSTRUCTIVO.md          # Descripción funcional original del proyecto
├── README.md               # Esta guía de despliegue y uso
└── deploy/data/mcp/        # Directorio montado para registry/tokens MCP (se crea con provision.sh)
```

## Desarrollo local

Puedes levantar los servicios de manera idéntica en tu máquina local usando Docker Desktop o Docker Engine. Asegúrate de que nada use el puerto 7860 ni 11435 en el host.

Para detener el stack:

```bash
docker compose -f deploy/docker-compose.yml down
```

## Variables clave para MCP

- `MCP_REGISTRY_JSON`: JSON inline con la definición de proveedores (prioridad sobre el archivo).
- `MCP_REGISTRY_PATH`: Ruta dentro del contenedor (por defecto `/data/mcp/registry.json`).
- `MCP_TOKEN_<PROVEEDOR>`: Token Bearer para cada proveedor configurado.
- `MCP_CA_BUNDLE`: Ruta a un bundle PEM opcional si necesitas confiar en una CA privada.
- `RAG_FAISS_TOPK`: Cantidad de documentos adicionales a recuperar cuando el router cae a FAISS.

> Usa `deploy/scripts/provision.sh` para generar `.env` y crear `deploy/data/mcp/` junto al resto de volúmenes.

## Smoke test después del deploy

Una vez que los contenedores estén arriba (`docker compose up -d`), comprueba:

```bash
curl -s http://localhost:7860/health | jq '{status, mcp: .mcp.enabled, metrics: (.mcp_metrics[0] // {})}'
```

Deberías ver `status: "ok"`, `mcp: true` cuando haya registro MCP válido, y latencias en `metrics`. Si falla algún proveedor, la respuesta mostrará el último error y se degradará automáticamente a FAISS.

## Licencia

Define una licencia acorde a tu proyecto (por ejemplo, MIT, Apache-2.0, etc.).
