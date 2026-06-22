# Proyectos de DieL

## Samanta RAG (proyecto insignia)

Asistente conversacional basado en RAG para negocios locales, en evolución hacia un
**sistema multi-agente**.

- Stack: FastAPI, Gradio, FAISS, Ollama, Docker Compose, Nginx + SSL.
- Arquitectura hexagonal: dominio, aplicación, infraestructura e interfaces.
- Ingesta incremental de documentos Markdown a un vector store FAISS.
- **Multi-tenant**: una sola instancia sirve varios proyectos (tenants), cada uno con
  su propia base vectorial, su prompt y su configuración de MCP.
- **Integración MCP (Model Context Protocol)**: Samanta consume un servidor MCP que
  consulta el sistema de Teatro Bar Cultural para responder sobre eventos en vivo.
  El MCP se readapta como herramienta (tool) dentro del grafo multi-agente.
- Embeddings desacoplados del proveedor de chat: chat con gpt-4o-mini (OpenAI) y
  embeddings con nomic-embed-text (Ollama).
- Demo: dieljob.online
- Valor de negocio: atención automatizada 24/7 con respuestas trazables.

## Gestor de eventos — Teatro Bar Cultural (en producción)

- Stack: Django, Bootstrap.
- Alta de eventos, carga de flyer y descripción, cartelera interna semanal.
- Automatización del registro diario de ventas y caja.
- Cálculo de horas laborales a partir de un lector de huellas.
- Hoy expone un **servidor MCP** que Samanta consume: un activo de alto valor y foso
  competitivo.

## GestionGastronomica (en evolución)

- Stack: Django, Tailwind CSS, Docker, con tests y CI.
- Reescritura del gestor gastronómico (línea Teatro Bar Cultural) sobre la plantilla
  propia **DjangoProyects**, con arquitectura limpia.
- Hereda y moderniza la gestión de eventos, ventas y operaciones del salón.

## Sistema de gestión para ferretería (en producción)

- Stack: Python puro + SQLite, servidor dedicado en Raspberry Pi (Raspbian).
- Buscador centralizado que unifica múltiples listas de proveedores en Excel.
- Integración con Google Drive (carpeta "Inbox") para procesar planillas automáticamente.
- Carritos por empleado, facturación A y B con impresoras fiscales, marcado de
  faltantes y generación de pedidos en PDF.

## GestionFerreteria (reescritura en Django)

- Stack: Django, Celery + Redis, Docker, CI/CD.
- Nueva versión del sistema de ferretería generada desde la plantilla **DjangoProyects**,
  con arquitectura limpia.
- Procesamiento en background con **colas de tareas** (Celery + Redis) para importaciones
  masivas de listas de proveedores.

## impresor_comandera (en desarrollo)

- Stack: Python, PySide6 (GUI), FastAPI, SQLite, python-escpos; empaquetado con py2exe
  para Windows.
- Servicio de impresión de comandas/tickets en impresoras de red **ESC/POS**.
- Unifica dos canales de entrada: API HTTP y un archivo sincronizado con Google Drive.
- Editor de plantillas de ticket, administración de impresoras, monitor de trabajos y
  reimpresiones controladas. Evolución del script original `comandera.py`.

## OutpostIdle (en desarrollo)

- Stack: Godot + FastAPI + Python (3.12+, gestionado con `uv`).
- MMORPG sandbox con economía impulsada por jugadores (trueque, monedas crafteables,
  bolsa de valores de precios históricos).
- Arquitectura cliente-servidor estricta: Godot solo render/UI/input; FastAPI toda la
  lógica de negocio, validación y persistencia.
- Sistema de profesiones, NPCs dinámicos (el personaje sigue activo al desconectarse),
  mundo vacío construido por los jugadores. Decisiones documentadas en ADRs.

## DjangoProyects (plantilla / activo propio)

- Stack: Django, arquitectura limpia, CLI unificado, Docker listo para producción.
- **GitHub Template Repository**: base reutilizable de la que se generan los proyectos
  derivados (p. ej. `GestionFerreteria` y `GestionGastronomica`).
- Sincronización bidireccional base ↔ derivados para propagar mejoras comunes.
- Es un **foso competitivo**: acelera el arranque de cada nuevo sistema de cliente.

## GeneradorTarjetasClubSocial

- Stack: Python, Flask, Pillow; gestión de dependencias con `uv`.
- App web que genera tarjetas de socios con **códigos de barras** a partir de un CSV.
- Previsualización en el navegador y exportación a **PDF en grilla** lista para imprimir.

## Generador de tarjetas QR A4 (dayana impresion qr)

- Stack: HTML + JS 100% client-side (PapaParse, SheetJS/xlsx, qrcode.js). Sin backend.
- Carga un CSV/Excel + logo y genera una grilla A4 de tarjetas con **código QR**, título
  y descripción, lista para imprimir o exportar a PDF desde el navegador.

## agente-ia (laboratorio de automatización)

- Stack: **n8n** + **Ollama** orquestados con Docker Compose.
- Entorno para diseñar flujos de automatización con LLMs locales; banco de pruebas para
  automatizaciones de clientes antes de productivizarlas.

## Portfolio personal

- Stack: Django, Bootstrap 5, Docker, Nginx, GitHub API.
- Exhibe proyectos con gráfico de contribuciones y commits recientes vía API de GitHub.
- Incluye un chat widget conectado a Samanta (tenant `portfolio`).

> Nota: el proyecto `wsp-diffusion-prep` (envíos por WhatsApp vía WAHA) quedó
> **deprecado** por cambios de políticas de WhatsApp y riesgo de baneo con librerías no
> oficiales. El canal de mensajería se reemplaza por email (IMAP/SMTP), Telegram Bot API
> o, si el cliente lo exige, la WhatsApp Cloud API oficial de Meta.
