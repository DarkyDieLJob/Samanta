# Experiencia de DieL

Desarrollando software desde 2022, con foco en sistemas reales que resuelven problemas
concretos: facturación electrónica, automatización de procesos, gestión de stock e
integración con hardware fiscal.

## Sistema de gestión para ferretería (2022 — producción)

Primer sistema en producción. Empezó como un buscador que unificaba muchas listas de
proveedores en Excel en un solo lugar y creció hasta:

- Servidor dedicado en Raspberry Pi.
- Procesamiento automático de planillas desde una carpeta "Inbox" en Google Drive.
- Gestión de carritos por empleado.
- Emisión de facturas A y B con impresoras fiscales.
- Marcado de faltantes y generación de pedidos en PDF.

## Teatro Bar Cultural (2024 — producción)

Gestor de eventos en Django, más automatizaciones internas:

- Alta de eventos, carga de flyers y cartelera semanal.
- Registro diario automatizado de ventas y caja.
- Cálculo de horas laborales desde el registro de un lector de huellas.
- Base del **servidor MCP** que hoy consume Samanta para responder sobre eventos.

## Transición a Arquitecto de Agentes de IA (2025 — presente)

- Evolución de Samanta de RAG simple a sistema multi-agente con orquestación.
- Patrón reutilizable: "agente que consume un MCP de un sistema externo" para conectar
  los sistemas de futuros clientes.
- Adopción de prácticas profesionales: idempotencia, validación, observabilidad,
  reintentos y despliegue en la nube.
- Laboratorio de automatización con **n8n + Ollama** (proyecto `agente-ia`) para
  prototipar flujos con LLMs locales antes de llevarlos a clientes.

## Plataforma propia y reescritura de sistemas (2025 — presente)

- Creación de **DjangoProyects**, una plantilla base (GitHub Template) con arquitectura
  limpia, CLI, Docker y sincronización base ↔ derivados: baja el costo de arranque de
  cada nuevo cliente.
- Reescritura de los sistemas legados sobre esa plantilla: **GestionFerreteria** (v4, con
  colas Celery + Redis) y **GestionGastronomica** (línea Teatro Bar Cultural).
- Sincronización bidireccional base ↔ derivados para propagar mejoras comunes.

## Utilidades e integración con hardware (continuo)

- `impresor_comandera`: servicio de impresión ESC/POS (PySide6 + FastAPI + SQLite) que
  unifica entrada por API y por archivo de Google Drive, empaquetado para Windows.
- Generadores de tarjetas para imprimir: con códigos de barras (Flask + Pillow) y con
  códigos QR en grilla A4 (100% en el navegador).

## Formación

Autodidacta en desarrollo de software (2022 — presente). Aprendizaje continuo mediante
proyectos reales, documentación oficial y comunidades open-source. Especialización en
Python, arquitectura de software, sistemas de agentes y despliegue con contenedores.
