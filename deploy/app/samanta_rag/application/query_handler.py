"""Casos de uso relacionados con consultas de usuarios."""

from __future__ import annotations

from dataclasses import dataclass

from typing import List, Optional, TYPE_CHECKING

from ..domain.entities import QueryResult, VectorStoreSummary
from ..domain.services import QueryService
from ..mcp.router import MCPRouter, MCPRouterAttempt

if TYPE_CHECKING:  # pragma: no cover
    from .answer_cache import AnswerCache


@dataclass
class QueryHandler:
    """Orquesta la interacción entre RAG estático y MCP dinámico."""

    query_service: QueryService
    mcp_router: Optional[MCPRouter] = None
    fallback_top_k: int = 0
    answer_cache: Optional["AnswerCache"] = None

    def run(self, question: str) -> QueryResult:
        question = question.strip()
        if not question:
            raise RuntimeError("Pregunta vacía")

        # 1) Caché de respuestas: solo cubre respuestas de RAG puro (las
        #    respuestas con datos en vivo de MCP nunca se cachean). El ruteo a
        #    MCP es determinista por texto, así que servir una respuesta
        #    cacheada (que por construcción fue RAG) es consistente.
        if self.answer_cache is not None:
            cached = self.answer_cache.lookup(question)
            if cached is not None:
                return cached

        result, used_live_data = self._generate(question)

        # 2) Registrar solo respuestas de RAG puro para no cachear datos en vivo.
        if self.answer_cache is not None and not used_live_data:
            try:
                self.answer_cache.record(question, result)
            except Exception:  # noqa: BLE001 - el caché nunca debe romper la respuesta
                pass
        return result

    def try_cached(self, question: str) -> Optional[QueryResult]:
        """Devuelve solo una respuesta cacheada (sin invocar el LLM), o None."""
        question = question.strip()
        if not question or self.answer_cache is None:
            return None
        return self.answer_cache.lookup(question)

    def _generate(self, question: str) -> tuple[QueryResult, bool]:
        """Ejecuta el pipeline RAG/MCP. Devuelve (resultado, usó_datos_en_vivo)."""
        rag_context: Optional[str] = None
        rag_sources: List[str] = []
        rag_error: Optional[str] = None
        top_k = self.fallback_top_k if self.fallback_top_k > 0 else None

        try:
            rag_context, rag_sources = self.query_service.build_context(question, top_k=top_k)
        except RuntimeError as exc:
            rag_error = str(exc)

        attempt: Optional[MCPRouterAttempt] = None
        mcp_result: Optional[QueryResult] = None
        if self.mcp_router:
            attempt = self.mcp_router.try_answer(question)
            if attempt and attempt.status == "success" and attempt.result:
                mcp_result = attempt.result

        if mcp_result and rag_context:
            combined_context = (
                f"Datos en vivo:\n{mcp_result.answer}\n\n"
                f"Contexto base:\n{rag_context}"
            )
            answer = self.query_service.generate_with_context(question, combined_context)
            sources = list(dict.fromkeys(mcp_result.sources + rag_sources))
            return QueryResult(answer=answer, sources=sources), True

        if mcp_result:
            return mcp_result, True

        if rag_context:
            answer = self.query_service.generate_with_context(question, rag_context)
            return QueryResult(answer=answer, sources=rag_sources), False

        degrade_message = attempt.message if attempt and attempt.message else rag_error
        if degrade_message:
            raise RuntimeError(degrade_message)

        raise RuntimeError("No se pudo generar respuesta")

    def summary(self) -> VectorStoreSummary:
        return self.query_service.summary()

    def refresh_vectorstore(self) -> None:
        self.query_service.refresh_vectorstore()

    def is_available(self) -> bool:
        return self.query_service.is_available()

    def mcp_registry_summary(self) -> dict[str, object]:
        if not self.mcp_router:
            return {"enabled": False}
        registry = self.mcp_router.registry_summary()
        return registry

    def mcp_metrics_snapshot(self) -> list[dict[str, object]]:
        if not self.mcp_router:
            return []
        return self.mcp_router.metrics_snapshot()
