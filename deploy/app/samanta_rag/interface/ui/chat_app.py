"""Construcción de la interfaz Gradio."""

from __future__ import annotations

from typing import List, Tuple

import gradio as gr

from ...bootstrap import AppContainer
from ...application.query_handler import QueryHandler
from ...domain.entities import VectorStoreSummary


DEFAULT_EXAMPLES = [
    "¿Cuál es el horario de atención?",
    "¿Qué promociones hay esta semana?",
    "Necesito contacto para reservas",
]


def _format_summary(summary: VectorStoreSummary) -> str:
    if summary.last_updated:
        last_updated_text = summary.last_updated.strftime("%Y-%m-%d %H:%M")
    else:
        last_updated_text = "No disponible"
    return (
        f"**Documentos indexados:** {summary.total_files} · "
        f"**Chunks:** {summary.total_chunks} · "
        f"**Última actualización:** {last_updated_text}"
    )


def create_gradio_blocks(container: AppContainer) -> gr.Blocks:
    handler = container.query_handler
    settings = container.settings
    examples = list(settings.example_questions) or DEFAULT_EXAMPLES

    def predict(message: str, history: List[Tuple[str, str]]):
        question = message.strip()
        if not question:
            return "Por favor escribe una pregunta."
        try:
            result = handler.run(question)
        except RuntimeError as exc:  # pragma: no cover - se muestra al usuario
            return f"No se pudo procesar la pregunta: {exc}"
        formatted_sources = "\n".join(f"- {source}" for source in result.sources)
        if formatted_sources:
            return f"{result.answer}\n\n**Fuentes:**\n{formatted_sources}"
        return result.answer

    summary = handler.summary()
    summary_text = _format_summary(summary)

    with gr.Blocks(theme=gr.themes.Soft(), analytics_enabled=False) as demo:
        gr.Markdown("# Samanta · Asistente del negocio local")
        gr.Markdown(summary_text)
        gr.Markdown(
            "Responde dudas frecuentes sobre productos, menús y eventos a partir de la información del negocio."
        )
        gr.ChatInterface(
            predict,
            title="Atención al cliente",
            examples=examples,
            cache_examples=False,
            textbox=gr.Textbox(placeholder="Ej. ¿Cuál es el menú del día?", container=True),
        )
        gr.Markdown(
            """⚠️ **Importante:** Si la respuesta no cubre tu duda o detectas información desactualizada,
            contacta con el personal del negocio para confirmarla."""
        )
    return demo
