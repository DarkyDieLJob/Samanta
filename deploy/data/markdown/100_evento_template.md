---
title: "[TITULO DEL EVENTO]"
aliases: []
tags: [evento, agenda]
updated: 2026-04-14
fecha: YYYY-MM-DD
puertas: HH:MM
showtime: HH:MM
tipo: "[[060_tipos_de_eventos|Tipo de evento]]"
espacio: "[[020_patio_cervecero|Patio Cervecero]]"
artistas: ["Nombre Artista 1", "Nombre Artista 2"]
entradas:
  precio: Por confirmar
  link: ""
  notas: "Promo Club: ver [[010_club_social|Club Social]]"
menu_recomendado: ["[[041_menu_minutas|Minutas]]", "[[045_menu_bebidas_con_alcohol|Bebidas con alcohol]]"]
estado: programado # programado | confirmado | reprogramado | cancelado
links:
  - [[030_eventos_semana_actual]]
  - [[031_eventos_mensuales]]
---

# [TITULO DEL EVENTO]

## Descripción breve
Resumen de 1–2 líneas sobre el evento, propuesta artística y público objetivo.

## Detalles
- Fecha: YYYY-MM-DD (día de la semana)
- Puertas: HH:MM
- Showtime: HH:MM
- Tipo: [[060_tipos_de_eventos|Tipo de evento]]
- Espacio: [[020_patio_cervecero|Patio Cervecero]]
- Artistas: Nombre Artista 1, Nombre Artista 2

## Entradas
- Precio: Por confirmar
- Link de venta/reserva: …
- Beneficios Club: ver [[010_club_social|Club Social de La Ferre]]

## Observaciones técnicas (placeholders)
- Sonido/iluminación requeridos: …
- Prueba de sonido: HH:MM
- Duración estimada: …

## Enlaces
- Agenda semanal: [[030_eventos_semana_actual]]
- Agenda mensual: [[031_eventos_mensuales]]
- Menú recomendado: [[040_menu_index|Ver carta]]

## Contexto para IA
- **Uso**: nota canónica del evento para respuestas precisas.

## Datos estructurados
- Evento { titulo, fecha, puertas, showtime, tipo_ref, espacio_ref, artistas[], precio, link, estado }
