# Despliegue del agente RAG en VPS

Este directorio contiene los archivos necesarios para levantar el agente conversacional basado en RAG dentro de un VPS con Docker Compose.

## Estructura

- `docker-compose.yml`: Orquesta los servicios `ollama`, `app` y `refresher`.
- `.env.example`: Variables de entorno de referencia. Copia a `.env` y ajusta según el VPS.
- `app/`: Código fuente del pipeline RAG (no versionado aquí por defecto).
- `data/markdown/`: Documentos en formato Markdown que alimentan la base de conocimiento.
- `data/vectorstore/`: Índices FAISS generados y persistidos.
- `data/mcp/`: JSONs privados del registry MCP si decides montarlos dentro de los contenedores.
- `logs/`: Directorio para logs de aplicación y tareas de refresco.

## Preparación

1. Instala Docker y Docker Compose en el VPS.
2. Copia este directorio al VPS, asegurando permisos adecuados.
3. Duplica `.env.example` a `.env` y ajusta rutas, modelo, parámetros del RAG y credenciales necesarias.
4. Coloca el contenido Markdown en `data/markdown/` y verifica que la app lo lea correctamente.
5. Opcional: añade scripts de ingestión o tests dentro de `app/` según tus necesidades.

## Despliegue inicial

```bash
cd deploy
cp .env.example .env  # editar luego
# Construye imagen de la app si el Dockerfile está disponible en app/
docker compose build app
# Descarga imágenes y levanta servicios
docker compose up -d
```

- La primera ejecución descargará el modelo `qwen3:8b` en el servicio `ollama`.
- El servicio `app` expondrá la interfaz Gradio en el puerto 7860; considera colocar un proxy inverso con HTTPS.
- El servicio `refresher` ejecuta el módulo `samanta_rag.ingest` en modo observación (`--watch`) para regenerar embeddings cuando cambien los Markdown.
- Endpoints de control disponibles:
  - `GET /health`: Estado general, resumen del índice y snapshot de métricas MCP.
  - `GET /api/status`: Estado detallado, resumen e IPs permitidas.
  - `POST /api/reload`: Recarga el vectorstore desde disco después de una ingesta.

## Configuración del ruteo MCP

1. Genera un archivo `deploy/data/mcp/registry.json` (u otro nombre) con la lista de proveedores y herramientas MCP.
2. En `.env`, define **uno** de los siguientes:
   - `MCP_REGISTRY_JSON` con el JSON inline (útil para pruebas).
   - `MCP_REGISTRY_PATH=/data/mcp/registry.json` si prefieres montar el archivo desde el host (el volumen `./data/mcp:/data/mcp:ro` ya está declarado).
3. Para cada proveedor define su token (`MCP_TOKEN_<NOMBRE>`). Solo se montarán los tokens listados en `docker-compose.yml`; añade los que necesites.
4. Si tu proveedor usa certificados internos, define `MCP_CA_BUNDLE=/data/mcp/ca.pem` (o ruta equivalente) y deposita el archivo en `deploy/data/mcp/`.

Las herramientas descubiertas se registran como `<proveedor>.<tool>` y el router decidirá si usa MCP o FAISS de acuerdo al intent. Ante fallas, se degrada con `RAG_FAISS_TOPK` documentos adicionales.

## Smoke tests recomendados

Tras `docker compose up -d`:

```bash
curl -s http://localhost:7860/health | jq
```

Verifica que `status` sea `ok`, `summary.documents_indexed > 0` y que la sección `mcp.enabled` sea `true` cuando cargues un registry válido. Los campos `mcp_metrics` mostrarán latencias p50/p95/p99 por herramienta.

## Mantenimiento

- Usa `docker compose logs <servicio>` para depurar.
- Para detener servicios: `docker compose down` (añade `--volumes` solo si quieres eliminar datos locales).
- Programa backups periódicos de `data/markdown/` y `data/vectorstore/`.
- Ajusta variables de chunking, temperatura y concurrencia en `.env` conforme evolucione la carga.
- Si deseas restringir el acceso al chatbot, define `ALLOWED_IPS` en `.env` con la lista de IPs permitidas. Cuando está vacío o en `*`, se acepta cualquier origen.
- Puedes personalizar las preguntas sugeridas en la interfaz de chat mediante `EXAMPLE_QUESTIONS` (separadas por `|`).
- Backup recomendado:
  - `data/markdown/` y `data/vectorstore/`: usar `rsync` o snapshots diarios.
  - `logs/`: rotar semanalmente y almacenar en almacenamiento frío si se requiere auditoría.
- Monitoreo sugerido:
  - Ejecutar `samanta-rag-diagnostics --api-url https://tu-dominio` tras cada despliegue o actualización de contenido.
  - Añadir healthchecks externos (p. ej. UptimeRobot) apuntando a `/health`.
