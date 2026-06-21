# Plan de ejecución — Samanta multi-tenant (1 VPS, varios proyectos)

> Este archivo vive en el repo **Samanta** y se ejecuta desde acá. El plan del lado
> del portfolio (widget + proxy + anti-abuso) está en el repo `portfolio`:
> `docs/plan-chat-widget-portfolio.md`.

## Objetivo

Servir varios proyectos (**tenants**) desde **una sola instancia** de Samanta en el VPS,
cada uno con:
- su **propia base vectorial FAISS**,
- su `SYSTEM_PROMPT`,
- su `retrieval_k` y `example_questions`,
- su **config de MCP** (on/off + proveedores).

Tenants iniciales: `teatro` (con MCP de eventos) y `portfolio` (perfil de DieL, MCP off).
Modelo de chat: **gpt-4o-mini** (OpenAI). Embeddings: **Ollama `nomic-embed-text`**.

## Estado actual del repo (base sobre la que construimos)

- Arquitectura hexagonal: `domain/` (puertos `VectorStorePort`, `ChatModelPort`), `application/` (`QueryHandler`), `infrastructure/` (FAISS, Ollama/OpenAI), `interface/` (api + ui gradio).
- `config.py`: un único `Settings` global desde env (singleton `settings`).
- `bootstrap.py`: crea **un** `QueryHandler` + adapta MCP desde env.
- `interface/api/dependencies.py`: guarda **un** handler global (`_QUERY_HANDLER`).
- `interface/api/routes.py`: `POST /api/query {question}` → `{answer, sources}`; `/health`, `/api/status`, `/api/reload`.
- `ingest.py`: indexa `settings.documents_path` → `settings.vectorstore_path` (markdown → FAISS, incremental por hash).
- `infrastructure/vectorstore/faiss_adapter.py`: carga **perezosa** del índice con lock y firma por metadata.

---

## F.0 — Desacoplar embeddings del proveedor de chat (CRÍTICO, hacer primero)

> **Problema detectado:** hoy el proveedor de embeddings se decide con `llm_provider`:
> - `ingest.py:206-209` y `faiss_adapter.py:55-58` usan `OpenAIEmbeddings` **si** `llm_provider == "openai"`.
>
> Eso significa que con `LLM_PROVIDER=openai` (chat con gpt-4o-mini) **los embeddings
> también pasarían a OpenAI**, contradiciendo "embeddings en Ollama". Hay que separarlos.

- [x] Agregar a `Settings` (en `config.py`) un campo independiente:
  ```python
  embedding_provider: Literal["ollama", "openai"] = "ollama"
  ```
  leído de `EMBEDDING_PROVIDER` (default `ollama`).
- [x] Crear un helper único para construir embeddings y usarlo en `ingest.py` y `faiss_adapter.py`:
  ```python
  # infrastructure/vectorstore/embeddings.py
  def build_embeddings(*, provider: str, model_name: str, ollama_base_url: str, openai_api_key: str):
      if provider == "openai" and openai_api_key:
          from langchain_openai import OpenAIEmbeddings
          return OpenAIEmbeddings(model=model_name, api_key=openai_api_key)
      from langchain_ollama import OllamaEmbeddings
      return OllamaEmbeddings(model=model_name, base_url=ollama_base_url)
  ```
- [x] Reemplazar los dos `if settings.llm_provider == "openai"` de embeddings por `build_embeddings(provider=settings.embedding_provider, ...)`. (Hecho a nivel `settings`; cuando exista `TenantConfig` se pasará `tenant.embedding_provider`.)
- [ ] **Reindexar** tras el cambio (los vectores de un proveedor no son compatibles con otro). _Pendiente solo si se cambia `EMBEDDING_PROVIDER`; hoy prod sigue en `ollama`._
- [x] Confirmar qué usa **producción** realmente: el `.env` actual NO define `LLM_PROVIDER` ni `EMBEDDING_PROVIDER`, por lo que ambos caen al default `ollama` (chat `qwen3:8b` + embeddings `nomic-embed-text`). No requiere reindex mientras no se cambie a OpenAI.

---

## F.1 — Modelo de datos del tenant (`config.py`)

- [x] Agregar `TenantConfig` (inmutable) con todo lo que varía por proyecto (se sumó `temperature` y `mcp_from_env` para retrocompat del MCP por env):
  ```python
  @dataclass(frozen=True)
  class TenantConfig:
      id: str
      system_prompt: str
      documents_path: Path
      vectorstore_path: Path
      llm_provider: str = "ollama"          # "ollama" | "openai"
      model_name: str = "qwen3:8b"
      embedding_provider: str = "ollama"
      embedding_model_name: str = "nomic-embed-text"
      retrieval_k: int = 4
      example_questions: Tuple[str, ...] = ()
      mcp_registry_path: Optional[Path] = None  # None = MCP desactivado
      enabled: bool = True
  ```
- [x] `load_tenants()`:
  - Lee el directorio `TENANTS_PATH` (default `/data/tenants`), un `*.json` por tenant.
  - Si no hay tenants definidos, construye **un tenant `default`** a partir del `Settings` global actual (retrocompatibilidad total).
  - Devuelve `Dict[str, TenantConfig]` y un `default_tenant_id` (env `DEFAULT_TENANT`, fallback al primero/`default`).
- [x] La `Settings` global queda para **infra compartida**: `ollama_base_url`, `openai_api_key`, `log_path`, `allowed_ips`, `max_concurrent_sessions`, `app_timezone`, `chunk_size`, `chunk_overlap`.

---

## F.2 — Registro de handlers por tenant (`bootstrap.py`)

- [x] `AppContainer` pasa a tener (con `query_handler` como property al default para retrocompat de Gradio):
  ```python
  @dataclass(frozen=True)
  class AppContainer:
      settings: Settings
      handlers: Dict[str, QueryHandler]
      default_tenant: str
      tenants: Dict[str, TenantConfig]
  ```
- [x] Extraer `build_handler(tenant: TenantConfig, settings: Settings) -> QueryHandler`:
  - Construye el `ChatPromptTemplate` con `tenant.system_prompt`.
  - `FAISSVectorStoreAdapter(tenant.vectorstore_path, embedding_model_name=tenant.embedding_model_name, ...)` — **pasar también `embedding_provider`** (ver F.0).
  - Elige `OpenAIChatModel` / `OllamaChatModel` según `tenant.llm_provider` + `settings.openai_api_key`.
  - `QueryService(..., top_k=tenant.retrieval_k)` y `QueryHandler(query_service=..., fallback_top_k=settings.rag_faiss_topk)`.
  - Si `tenant.mcp_registry_path`: cargar registry de ese path, `build_tool_registry`, `MCPRouter` y asignar `handler.mcp_router`. Si es `None`, MCP desactivado.
- [x] `create_container()` itera `load_tenants()` y arma `handlers = {id: build_handler(t, settings)}` (solo `enabled`).
- [x] **Carga perezosa garantizada:** el `FAISSVectorStoreAdapter` ya hace lazy-load del índice (no se toca RAM hasta la primera consulta del tenant). Construir el handler es barato. (Además ahora recibe `embedding_provider`/`openai_api_key` por tenant.)

---

## F.3 — Resolución por tenant (`interface/api/dependencies.py`)

- [x] Reemplazar el handler único por un registro:
  ```python
  _HANDLERS: Dict[str, QueryHandler] = {}
  _DEFAULT_TENANT: str = "default"

  def configure_dependencies(handlers, default_tenant, settings): ...

  def get_query_handler(tenant: Optional[str] = None) -> QueryHandler:
      key = tenant or _DEFAULT_TENANT
      handler = _HANDLERS.get(key)
      if handler is None:
          raise KeyError(key)
      return handler
  ```

---

## F.4 — API por tenant (`interface/api/routes.py`)

- [x] `QueryPayload` acepta `tenant` opcional (retrocompat: si falta, usa default):
  ```python
  class QueryPayload(BaseModel):
      question: str
      tenant: str | None = None
  ```
- [x] En `/api/query`, resolver handler y devolver 404 si el tenant no existe:
  ```python
  try:
      handler = get_query_handler(payload.tenant)
  except KeyError:
      raise HTTPException(status_code=404, detail="Tenant desconocido")
  ```
- [x] `/health`, `/api/status`, `/api/reload` aceptan `?tenant=` opcional (default si falta). `/api/status` lista `tenants` y `default_tenant`.
- [x] **El contrato actual no se rompe:** sin `tenant`, todo funciona como hoy (tenant `default`).

---

## F.5 — Ingesta por tenant (`ingest.py`)

- [x] Refactor `ingest_once(tenant: TenantConfig)` usando `tenant.documents_path` / `tenant.vectorstore_path` / `tenant.embedding_provider` / `tenant.embedding_model_name` (en vez del `settings` global).
- [x] CLI:
  - `--tenant <id>`: ingesta ese tenant.
  - `--all`: ingesta todos los tenants habilitados.
  - sin flags: tenant `default` (retrocompat, resuelto por `load_tenants`).
- [x] `--watch`: observar el `documents_path` de cada tenant (un observer por tenant) y reindexar el índice correcto.
- [x] Revisar el guard de borrado en `build_vectorstore` (`mount_roots`): con subdir `/data/vectorstore/<tenant>` hace `shutil.rmtree(subdir)` (correcto, solo borra el índice de ese tenant).

---

## F.6 — Paquetes de configuración (`deploy/data/tenants/*.json`)

- [x] `deploy/data/tenants/teatro.json` (creado; `mcp_registry_path` apunta al existente `/data/mcp/registry.json`):
  ```json
  {
    "id": "teatro",
    "system_prompt": "Eres el asistente del Teatro Bar Cultural...",
    "documents_path": "/data/markdown/teatro",
    "vectorstore_path": "/data/vectorstore/teatro",
    "llm_provider": "openai",
    "model_name": "gpt-4o-mini",
    "embedding_provider": "ollama",
    "embedding_model_name": "nomic-embed-text",
    "retrieval_k": 4,
    "example_questions": ["¿Qué eventos hay esta semana?", "¿Cuál es el horario?"],
    "mcp_registry_path": "/data/mcp/teatro-registry.json",
    "enabled": true
  }
  ```
- [x] `deploy/data/tenants/portfolio.json` (creado):
  ```json
  {
    "id": "portfolio",
    "system_prompt": "Sos el asistente del portfolio de DieL (Arquitecto de Agentes de IA). Respondé sobre su perfil, proyectos, experiencia y stack usando solo el contexto. Si no sabés, sugerí el formulario de contacto.",
    "documents_path": "/data/markdown/portfolio",
    "vectorstore_path": "/data/vectorstore/portfolio",
    "llm_provider": "openai",
    "model_name": "gpt-4o-mini",
    "embedding_provider": "ollama",
    "embedding_model_name": "nomic-embed-text",
    "retrieval_k": 4,
    "example_questions": ["¿Quién es DieL?", "¿Qué proyectos hizo?", "¿Con qué tecnologías trabaja?"],
    "mcp_registry_path": null,
    "enabled": true
  }
  ```

---

## F.7 — Corpus del tenant `portfolio` (perfil de DieL)

- [x] Crear `deploy/data/markdown/portfolio/` con: `sobre-mi.md`, `proyectos.md`, `experiencia.md`, `stack.md`, `contacto.md`. (Contenido extraído del repo `portfolio` con el nuevo posicionamiento de Arquitecto de Agentes de IA.)
- [ ] Indexar (requiere Ollama corriendo): `uv run python -m samanta_rag.ingest --tenant portfolio`. _Paso de deploy._
- [ ] Verificar: `POST /api/query {"question":"¿Quién es DieL?","tenant":"portfolio"}`. _Paso de deploy._

> **Nota:** el markdown del teatro se movió de `deploy/data/markdown/*.md` a `deploy/data/markdown/teatro/` para aislar tenants. El deploy debe reindexar teatro también.

---

## F.8 — Despliegue (`deploy/docker-compose.yml`, `.env`)

- [x] Montar volumen `./data/tenants:/data/tenants:ro` (app y refresher); `./data/markdown` / `./data/vectorstore` ya montados. Se exponen `TENANTS_PATH`, `DEFAULT_TENANT`, `LLM_PROVIDER`, `EMBEDDING_PROVIDER`, `OPENAI_API_KEY` al contenedor.
- [ ] `.env` (acción manual del deploy): setear `LLM_PROVIDER=openai`, `OPENAI_API_KEY=...`, `MODEL_NAME=gpt-4o-mini`, `EMBEDDING_PROVIDER=ollama`, `TENANTS_PATH=/data/tenants`, `DEFAULT_TENANT=teatro`. _`.env.example` ya documenta estas vars._
- [x] El `refresher` corre `ingest --all --watch`.
- [ ] **Seguridad:** dejar `ALLOWED_IPS` con la IP del servidor del portfolio (el proxy Django es el único cliente público). _Acción de deploy._

---

## F.9 — Pruebas

- [x] Tests de `load_tenants()` (carga JSON, fallback default, DEFAULT_TENANT, JSON inválido, inmutabilidad, resolución de paths relativos, preservación de absolutos).
- [x] Test de aislamiento: una consulta a `portfolio` no devuelve fuentes del `teatro`.
- [x] Test de `/api/query` con `tenant` inexistente → 404.
- [x] Test retrocompat: `/api/query` sin `tenant` → usa default.
- [x] Test de `/api/status` lista tenants y default; `/api/reload` y `/health` resuelven `?tenant=`.
- [x] `pytest` añadido como dev dependency. Configuración `[tool.pytest.ini_options] pythonpath = ["."]` para que funcione `uv run pytest`.

Comando:

```bash
uv run pytest tests/ -v
```

Resultado: **14 passed**.

## Notas de robustez agregadas post-implementación

- `logging_utils.configure_logging` ahora tolera el path `/logs` sin permisos en local: cae a `./logs` y, si tampoco se puede, solo consola.
- Los JSONs de tenant usan paths relativos (`../markdown/<tenant>`, `../vectorstore/<tenant>`, `../mcp/registry.json`) que `config.py` resuelve desde el directorio del propio JSON. Esto hace que los mismos archivos funcionen dentro de Docker y en desarrollo local.

---

## Orden de ejecución (este repo)

1. **F.0** Desacoplar embeddings (+ reindex). Confirmar config real de prod.
2. **F.1–F.4** Multi-tenant en código (config, bootstrap, dependencies, routes).
3. **F.6** Crear los JSON de `teatro` y `portfolio`.
4. **F.5** Ingesta por tenant.
5. **F.7** Corpus del portfolio + ingest + pruebas.
6. **F.8** Compose/.env y deploy.
7. **F.9** Tests.

> Mantener SIEMPRE el contrato `POST /api/query` retrocompatible (tenant opcional) para
> no romper el deploy actual del teatro mientras se migra.
