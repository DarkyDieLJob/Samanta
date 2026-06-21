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

## Sistema de gestión para ferretería (en producción)

- Stack: Python puro + SQLite, servidor dedicado en Raspberry Pi (Raspbian).
- Buscador centralizado que unifica múltiples listas de proveedores en Excel.
- Integración con Google Drive (carpeta "Inbox") para procesar planillas automáticamente.
- Carritos por empleado, facturación A y B con impresoras fiscales, marcado de
  faltantes y generación de pedidos en PDF.

## OutpostIdle (en desarrollo)

- Stack: Godot + FastAPI + Python.
- MMORPG sandbox con economía impulsada por jugadores.
- Arquitectura cliente-servidor: Godot para render/UI, FastAPI para lógica y persistencia.

## Portfolio personal

- Stack: Django, Bootstrap 5, Docker, Nginx, GitHub API.
- Exhibe proyectos con gráfico de contribuciones y commits recientes vía API de GitHub.
- Incluye un chat widget conectado a Samanta (tenant `portfolio`).

> Nota: el proyecto `wsp-diffusion-prep` (envíos por WhatsApp vía WAHA) quedó
> **deprecado** por cambios de políticas de WhatsApp y riesgo de baneo con librerías no
> oficiales. El canal de mensajería se reemplaza por email (IMAP/SMTP), Telegram Bot API
> o, si el cliente lo exige, la WhatsApp Cloud API oficial de Meta.
