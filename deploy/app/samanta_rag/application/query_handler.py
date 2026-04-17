"""Casos de uso relacionados con consultas de usuarios."""

from __future__ import annotations

from dataclasses import dataclass

from typing import Optional

from ..domain.entities import QueryResult, VectorStoreSummary
from ..domain.services import QueryService
from ..mcp.router import MCPRouter, MCPRouterAttempt


@dataclass
class QueryHandler:
    """Orquesta la interacción entre RAG estático y MCP dinámico."""

    query_service: QueryService
    mcp_router: Optional[MCPRouter] = None
    fallback_top_k: int = 0

    def run(self, question: str) -> QueryResult:
        question = question.strip()
        if not question:
            raise RuntimeError("Pregunta vacía")
        attempt: Optional[MCPRouterAttempt] = None
        if self.mcp_router:
            attempt = self.mcp_router.try_answer(question)
            if attempt and attempt.status == "success" and attempt.result:
                return attempt.result
        degrade_message = attempt.message if attempt and attempt.message else None
        top_k = self.fallback_top_k if self.fallback_top_k > 0 else None
        result = self.query_service.run(question, top_k=top_k)
        if degrade_message:
            answer = f"{degrade_message}. Utilizando base estática.\n\n{result.answer}"
            sources = list(result.sources)
            if "FAISS estático" not in sources:
                sources.append("FAISS estático")
            return QueryResult(answer=answer, sources=sources)
        return result

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
