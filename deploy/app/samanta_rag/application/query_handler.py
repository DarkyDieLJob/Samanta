"""Casos de uso relacionados con consultas de usuarios."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.entities import QueryResult, VectorStoreSummary
from ..domain.services import QueryService


@dataclass
class QueryHandler:
    """Orquesta la interacción entre dominios y adapters."""

    query_service: QueryService

    def run(self, question: str) -> QueryResult:
        return self.query_service.run(question)

    def summary(self) -> VectorStoreSummary:
        return self.query_service.summary()

    def refresh_vectorstore(self) -> None:
        self.query_service.refresh_vectorstore()

    def is_available(self) -> bool:
        return self.query_service.is_available()
