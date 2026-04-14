"""Adaptador de vectorstore basado en FAISS."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import List, Optional

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings

from ...constants import METADATA_FILENAME
from ...domain.entities import RetrievedDocument, VectorStorePort, VectorStoreSummary

LOGGER = logging.getLogger(__name__)


class FAISSVectorStoreAdapter(VectorStorePort):
    """Gestiona carga perezosa y consultas sobre un índice FAISS."""

    def __init__(self, vectorstore_path: Path, *, embedding_model_name: str, base_url: str) -> None:
        self._vectorstore_path = vectorstore_path
        self._vectorstore: Optional[FAISS] = None
        self._signature: Optional[str] = None
        self._lock = Lock()
        self._embedding_model_name = embedding_model_name
        self._base_url = base_url

    # --- Utilidades internas -------------------------------------------------

    @property
    def _metadata_file(self) -> Path:
        return self._vectorstore_path / METADATA_FILENAME

    def _compute_signature(self) -> Optional[str]:
        if not self._metadata_file.exists():
            return None
        stats = self._metadata_file.stat()
        return f"{stats.st_mtime}-{stats.st_size}"

    def _load_vectorstore(self) -> Optional[FAISS]:
        if not self._metadata_file.exists():
            LOGGER.warning("No se encontró metadata en %s", self._metadata_file)
            return None
        if not self._vectorstore_path.exists():
            LOGGER.warning("El directorio de vectorstore %s no existe", self._vectorstore_path)
            return None
        embeddings = OllamaEmbeddings(model=self._embedding_model_name, base_url=self._base_url)
        return FAISS.load_local(
            folder_path=str(self._vectorstore_path),
            embeddings=embeddings,
            allow_dangerous_deserialization=True,
        )

    def _ensure_loaded(self) -> Optional[FAISS]:
        with self._lock:
            signature = self._compute_signature()
            if signature is None:
                self._vectorstore = None
                self._signature = None
                return None
            if self._vectorstore is not None and self._signature == signature:
                return self._vectorstore
            LOGGER.info("Cargando vectorstore FAISS desde disco...")
            vectorstore = self._load_vectorstore()
            self._vectorstore = vectorstore
            self._signature = signature if vectorstore else None
            return vectorstore

    def _to_retrieved_documents(self, docs: List[Document]) -> List[RetrievedDocument]:
        result: List[RetrievedDocument] = []
        for doc in docs:
            content = doc.page_content
            source = str(doc.metadata.get("source", "desconocido"))
            result.append(RetrievedDocument(content=content, source=source))
        return result

    # --- Implementación del puerto ------------------------------------------

    def retrieve(self, question: str, k: int) -> List[RetrievedDocument]:  # type: ignore[override]
        vectorstore = self._ensure_loaded()
        if not vectorstore:
            return []
        retriever = vectorstore.as_retriever(search_kwargs={"k": k})
        raw_docs = retriever.get_relevant_documents(question)
        return self._to_retrieved_documents(raw_docs)

    def refresh(self) -> None:  # type: ignore[override]
        with self._lock:
            self._vectorstore = None
            self._signature = None

    def is_available(self) -> bool:  # type: ignore[override]
        return self._ensure_loaded() is not None

    def summary(self) -> VectorStoreSummary:  # type: ignore[override]
        metadata_file = self._metadata_file
        if not metadata_file.exists():
            return VectorStoreSummary(total_files=0, total_chunks=0, last_updated=None)
        try:
            data = json.loads(metadata_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            LOGGER.warning("Metadata inválida en %s", metadata_file)
            timestamp = metadata_file.stat().st_mtime
            last_updated = datetime.fromtimestamp(timestamp)
            return VectorStoreSummary(total_files=0, total_chunks=0, last_updated=last_updated)
        total_files = len(data)
        total_chunks = sum(int(item.get("chunk_count", 0)) for item in data)
        timestamp = metadata_file.stat().st_mtime
        last_updated = datetime.fromtimestamp(timestamp)
        return VectorStoreSummary(total_files=total_files, total_chunks=total_chunks, last_updated=last_updated)
