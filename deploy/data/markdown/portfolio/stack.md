# Stack técnico de DieL

## Núcleo (su fuerte)

- **Python** — lenguaje principal.
- **FastAPI** — APIs de alto rendimiento y exposición de agentes.
- **Django** — aplicaciones web completas y paneles de gestión.
- **Docker / Docker Compose** — empaquetado y orquestación de servicios.
- **Linux / VPS / Bash** — despliegue y operación.
- **Nginx** — reverse proxy y SSL.
- **PostgreSQL / SQLite** — persistencia.
- **Git / GitHub** — control de versiones.

## Agentes de IA y RAG

- **RAG** (Retrieval Augmented Generation) sobre datos propios del cliente.
- **Bases vectoriales**: FAISS (en producción con Samanta); experiencia trasladable a
  Qdrant y Chroma.
- **Embeddings**: nomic-embed-text vía Ollama; OpenAI text-embedding cuando aplica.
- **Modelos de chat**: gpt-4o-mini (OpenAI) y modelos locales con Ollama (qwen3:8b).
- **MCP (Model Context Protocol)**: integración de sistemas externos como herramientas
  del agente.
- **Pydantic** — validación de inputs/outputs de cada agente.
- Hacia LangGraph para orquestación multi-agente (grafos de estado, memoria).

## Capas profesionales (en cada proyecto)

- Idempotencia (no procesar el mismo evento dos veces).
- Reintentos con backoff en llamadas a LLMs y bases vectoriales.
- Observabilidad: logs de invocaciones, tokens, latencia y errores.
- Gestión de secretos y configuración por entorno.
- Despliegue en la nube (sin depender de la máquina local).

## Plataforma y automatización

- **DjangoProyects**: plantilla base (GitHub Template) con arquitectura limpia, CLI
  unificado y dockerización; genera proyectos derivados con sync bidireccional.
- **Celery + Redis**: colas de tareas y procesamiento en background.
- **n8n + Ollama**: automatización de flujos con LLMs locales.
- **CI/CD** y tooling de calidad (tests, pre-commit) en los proyectos sobre la plantilla.

## Complementos

- JavaScript, HTML/CSS, Bootstrap, Tailwind CSS.
- **Flask** y **PySide6** (apps de escritorio y utilidades web puntuales).
- Godot / GDScript (videojuegos).
- APIs REST e integración con hardware: impresoras fiscales, impresoras **ESC/POS**
  (python-escpos), lectores de huella, generación de códigos de barras y **QR**.
- Google Drive API; gestión de dependencias con `uv`.
