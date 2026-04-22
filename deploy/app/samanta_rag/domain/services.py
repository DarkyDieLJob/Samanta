"""Servicios de dominio para Samanta RAG."""

from __future__ import annotations

from typing import List, Optional, Tuple

from .entities import (
    ChatModelPort,
    QueryResult,
    RetrievedDocument,
    VectorStorePort,
    VectorStoreSummary,
)


def format_context(documents: List[RetrievedDocument]) -> str:
    if not documents:
        return ""
    chunks = [f"Fuente: {doc.source}\n{doc.content}" for doc in documents]
    return "\n\n".join(chunks)


def extract_sources(documents: List[RetrievedDocument]) -> List[str]:
    seen = set()
    sources: List[str] = []
    for doc in documents:
        if doc.source not in seen:
            sources.append(doc.source)
            seen.add(doc.source)
    return sources


class QueryService:
    """Orquestador principal para responder preguntas."""

    def __init__(self, vectorstore: VectorStorePort, chat_model: ChatModelPort, *, top_k: int) -> None:
        self._vectorstore = vectorstore
        self._chat_model = chat_model
        self._top_k = top_k

    def run(self, question: str, *, top_k: Optional[int] = None) -> QueryResult:
        context, sources = self.build_context(question, top_k=top_k)
        answer = self._chat_model.generate(question, context)
        return QueryResult(answer=answer, sources=sources)

    def build_context(self, question: str, *, top_k: Optional[int] = None) -> Tuple[str, List[str]]:
        if not self._vectorstore.is_available():
            raise RuntimeError("Vectorstore no disponible")
        effective_k = self._top_k
        if top_k is not None and top_k > 0:
            effective_k = top_k
        documents = self._vectorstore.retrieve(question, effective_k)
        if not documents:
            raise RuntimeError("No se encontraron documentos relevantes")
        context = format_context(documents)
        sources = extract_sources(documents)
        return context, sources

    def generate_with_context(self, question: str, context: str) -> str:
        return self._chat_model.generate(question, context)

    def summary(self) -> VectorStoreSummary:
        return self._vectorstore.summary()

    def refresh_vectorstore(self) -> None:
        self._vectorstore.refresh()

    def is_available(self) -> bool:
        return self._vectorstore.is_available()
