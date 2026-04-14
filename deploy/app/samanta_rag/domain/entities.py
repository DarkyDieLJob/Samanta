"""Entidades y puertos del dominio Samanta RAG."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Protocol


@dataclass(frozen=True)
class RetrievedDocument:
    """Fragmento recuperado desde el vectorstore."""

    content: str
    source: str


@dataclass(frozen=True)
class QueryResult:
    """Respuesta final entregada al usuario."""

    answer: str
    sources: List[str]


@dataclass(frozen=True)
class VectorStoreSummary:
    """Resumen del índice vectorial."""

    total_files: int
    total_chunks: int
    last_updated: Optional[datetime]

    def to_dict(self) -> dict[str, object]:
        return {
            "files": self.total_files,
            "chunks": self.total_chunks,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }


class VectorStorePort(Protocol):
    """Puerto que expone las operaciones principales del vectorstore."""

    def retrieve(self, question: str, k: int) -> List[RetrievedDocument]:
        """Obtiene los fragmentos más relevantes para la pregunta."""

    def refresh(self) -> None:
        """Invalida cualquier caché local del vectorstore."""

    def is_available(self) -> bool:
        """Indica si el índice está listo para recibir consultas."""

    def summary(self) -> VectorStoreSummary:
        """Retorna un resumen de estado del índice."""


class ChatModelPort(Protocol):
    """Puerto para modelos conversacionales."""

    def generate(self, question: str, context: str) -> str:
        """Genera una respuesta usando la pregunta y el contexto proporcionado."""
