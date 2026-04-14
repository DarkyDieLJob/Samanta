---
title: Tipos de eventos
aliases: [Taxonomía eventos, Tipos]
tags: [eventos, tipos, tecnica]
updated: 2026-04-14
links:
  - [[000_index]]
  - [[020_patio_cervecero]]
  - [[030_eventos_semana_actual]]
  - [[050_horarios]]
---

# Tipos de eventos

## Presentaciones de libros
- Formato: charla/lectura + Q&A
- Técnica mínima: micrófono x1–2, parlante, mesa, sillas
- Enlace: [[020_patio_cervecero|Patio Cervecero]] (si clima acompaña)

## Exposición de cuadros
- Formato: montaje + inauguración
- Técnica mínima: panelería/soportes, iluminación puntual (a confirmar)

## Bandas
- Formato: eléctrico/acústico
- Técnica mínima: PA, micrófonos, DI, monitoreo (por confirmar)
- Considerar espacio y vecinos; ver [[050_horarios|Horarios]]

## Solistas
- Formato: voz + instrumento
- Técnica mínima: 1–2 canales

## Stand-up / Escénicas
- Formato: monólogo/varieté
- Técnica mínima: micrófono de mano, luz frente

## Contexto para IA
- **Ruteo**: mapear consultas a este catálogo y derivar a agenda semanal/mensual.

## Datos estructurados
- TipoEvento { nombre: str, tecnica_minima: [str], sugerido_para: [espacio_ref] }
