"""Módulo de ingestión de documentos Markdown al vectorstore FAISS."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Dict, Iterable, List, Optional, Tuple

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    MarkdownHeaderTextSplitter,
)
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .config import TenantConfig, load_tenants, settings
from .infrastructure.vectorstore.embeddings import build_embeddings
from .constants import METADATA_FILENAME, SUPPORTED_EXTENSIONS
from .logging_utils import configure_logging

LOGGER = logging.getLogger(__name__)


@dataclass
class IngestStats:
    processed_files: int
    total_chunks: int
    duration_seconds: float
    updated: bool


@dataclass
class FileMetadata:
    source: str
    hash: str
    mtime: float
    chunk_count: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "source": self.source,
            "hash": self.hash,
            "mtime": self.mtime,
            "chunk_count": self.chunk_count,
        }


class MarkdownWatcher(FileSystemEventHandler):
    """Observa cambios en los archivos markdown y dispara la reindexación."""

    def __init__(self, callback, debounce_seconds: float = 5.0) -> None:
        self._callback = callback
        self._debounce_seconds = debounce_seconds
        self._last_run = 0.0

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if Path(event.src_path).suffix.lower() not in SUPPORTED_EXTENSIONS:
            return
        now = time.time()
        if now - self._last_run < self._debounce_seconds:
            LOGGER.debug("Evento ignorado por debounce: %s", event)
            return
        LOGGER.info("Detección de cambios en %s. Reindexando...", event.src_path)
        self._last_run = now
        self._callback()


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def collect_markdown_documents(root: Path) -> List[Path]:
    files: List[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(path)
    return files


def load_documents(files: Iterable[Path], base_path: Path) -> Tuple[List[Document], List[FileMetadata]]:
    """Carga documentos Markdown y los divide respetando secciones por encabezados.

    - Primero divide por encabezados (h1, h2, h3) para preservar contexto semántico.
    - Luego aplica un splitter recursivo para ajustar a chunk_size/overlap.
    - Propaga metadatos como source y headers a cada chunk.
    """
    section_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")]
    )
    chunk_splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    documents: List[Document] = []
    metadata_entries: List[FileMetadata] = []
    for file_path in files:
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            LOGGER.warning("No se pudo leer el archivo %s en UTF-8", file_path)
            continue
        if not text.strip():
            LOGGER.debug("Archivo vacío: %s", file_path)
            continue
        rel_path = file_path.relative_to(base_path)
        content_hash = hash_text(text)
        # Divide en secciones por encabezados
        sections = section_splitter.split_text(text)
        section_docs: List[Document] = []
        for sec in sections:
            sec_text = sec.page_content
            # Metadatos de encabezados (si existen)
            header_meta = {k: v for k, v in sec.metadata.items() if k in {"h1", "h2", "h3"}}
            # Chunks por sección
            chunks = chunk_splitter.split_text(sec_text)
            for chunk in chunks:
                metadata = {
                    "source": str(rel_path),
                    "mtime": file_path.stat().st_mtime,
                    "hash": content_hash,
                    **header_meta,
                }
                section_docs.append(Document(page_content=chunk, metadata=metadata))

        metadata_entries.append(
            FileMetadata(
                source=str(rel_path),
                hash=content_hash,
                mtime=file_path.stat().st_mtime,
                chunk_count=len(section_docs),
            )
        )
        # Añade índice de chunk
        for idx, doc in enumerate(section_docs):
            doc.metadata["chunk_index"] = idx
            documents.append(doc)
    return documents, metadata_entries


def persist_metadata(vectorstore_path: Path, metadata_entries: List[FileMetadata]) -> None:
    metadata_file = vectorstore_path / METADATA_FILENAME
    data = [entry.to_dict() for entry in metadata_entries]
    metadata_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_previous_metadata(vectorstore_path: Path) -> Dict[str, FileMetadata]:
    metadata_file = vectorstore_path / METADATA_FILENAME
    if not metadata_file.exists():
        return {}
    try:
        raw_data = json.loads(metadata_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOGGER.warning("No se pudo leer metadata previa, se regenerará el índice completo")
        return {}
    metadata: Dict[str, FileMetadata] = {}
    for entry in raw_data:
        try:
            metadata[entry["source"]] = FileMetadata(
                source=entry["source"],
                hash=entry["hash"],
                mtime=float(entry["mtime"]),
                chunk_count=int(entry.get("chunk_count", 0)),
            )
        except (KeyError, TypeError, ValueError):
            LOGGER.debug("Entrada inválida en metadata previa: %s", entry)
    return metadata


def metadata_changed(
    new_entries: List[FileMetadata],
    previous_entries: Dict[str, FileMetadata],
) -> bool:
    if len(new_entries) != len(previous_entries):
        return True
    for entry in new_entries:
        prev = previous_entries.get(entry.source)
        if not prev:
            return True
        if entry.hash != prev.hash or entry.chunk_count != prev.chunk_count:
            return True
    return False


def build_vectorstore(
    documents: List[Document],
    metadata_entries: List[FileMetadata],
    vectorstore_path: Path,
    *,
    embedding_provider: str = None,  # type: ignore[assignment]
    embedding_model_name: str = None,  # type: ignore[assignment]
) -> Optional[FAISS]:
    if not documents:
        LOGGER.warning("No se encontraron documentos para indexar. Se mantiene el índice anterior.")
        return None
    # Selección de embeddings según proveedor (independiente del chat)
    embeddings = build_embeddings(
        provider=embedding_provider or settings.embedding_provider,
        model_name=embedding_model_name or settings.embedding_model_name,
        ollama_base_url=settings.ollama_base_url,
        openai_api_key=settings.openai_api_key,
    )
    vectorstore = FAISS.from_documents(documents, embeddings)
    # Manejo seguro de borrado en raíces montadas
    safe_path = vectorstore_path
    mount_roots = {Path("/data/vectorstore").resolve()}
    if safe_path.exists():
        if safe_path.resolve() in mount_roots:
            # Borrar solo el contenido dentro del directorio montado
            for child in safe_path.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    try:
                        child.unlink()
                    except FileNotFoundError:
                        pass
        else:
            shutil.rmtree(safe_path)
    safe_path.mkdir(parents=True, exist_ok=True)
    vectorstore.save_local(str(safe_path))
    persist_metadata(safe_path, metadata_entries)
    LOGGER.info("Vectorstore FAISS almacenado en %s", safe_path)
    return vectorstore


def ingest_once(tenant: TenantConfig) -> Optional[IngestStats]:
    start = time.time()
    documents_dir = tenant.documents_path
    if not documents_dir.exists():
        LOGGER.error("[%s] El directorio de documentos %s no existe", tenant.id, documents_dir)
        return None
    document_files = collect_markdown_documents(documents_dir)
    documents, metadata_entries = load_documents(document_files, documents_dir)
    LOGGER.info(
        "[%s] Recopilados %d documentos y %d chunks", tenant.id, len(document_files), len(documents)
    )

    previous_metadata = load_previous_metadata(tenant.vectorstore_path)
    needs_update = metadata_changed(metadata_entries, previous_metadata)
    if not needs_update and tenant.vectorstore_path.exists():
        LOGGER.info("[%s] Sin cambios en los documentos. Se omite la reindexación.", tenant.id)
        duration = time.time() - start
        return IngestStats(
            processed_files=len(document_files),
            total_chunks=len(documents),
            duration_seconds=duration,
            updated=False,
        )

    vectorstore = build_vectorstore(
        documents,
        metadata_entries,
        tenant.vectorstore_path,
        embedding_provider=tenant.embedding_provider,
        embedding_model_name=tenant.embedding_model_name,
    )
    duration = time.time() - start
    return IngestStats(
        processed_files=len(document_files),
        total_chunks=len(documents),
        duration_seconds=duration,
        updated=vectorstore is not None,
    ) if vectorstore else None


def watch_documents(tenants: List[TenantConfig]) -> None:
    observer = Observer()
    for tenant in tenants:
        if not tenant.documents_path.exists():
            LOGGER.warning(
                "[%s] No se observa %s (no existe)", tenant.id, tenant.documents_path
            )
            continue
        event_handler = MarkdownWatcher(lambda t=tenant: _safe_ingest(t))
        observer.schedule(event_handler, str(tenant.documents_path), recursive=True)
        LOGGER.info("[%s] Monitoreo de documentos iniciado en %s", tenant.id, tenant.documents_path)
    observer.start()

    stop_event = Event()

    def handle_sig(signum, frame):  # type: ignore[override]
        LOGGER.info("Señal %s recibida. Deteniendo monitoreo...", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    try:
        while not stop_event.is_set():
            time.sleep(1)
    finally:
        observer.stop()
        observer.join()


def _safe_ingest(tenant: TenantConfig) -> None:
    try:
        stats = ingest_once(tenant)
        if stats and stats.updated:
            LOGGER.info(
                "[%s] Ingesta completada: %d archivos, %d chunks en %.2fs",
                tenant.id,
                stats.processed_files,
                stats.total_chunks,
                stats.duration_seconds,
            )
        elif stats:
            LOGGER.info(
                "[%s] Ingesta saltada: %d archivos revisados sin cambios relevantes",
                tenant.id,
                stats.processed_files,
            )
    except Exception:  # noqa: BLE001
        LOGGER.exception("[%s] Fallo durante la ingesta", tenant.id)


def _select_tenants(tenant_id: Optional[str], all_tenants: bool) -> List[TenantConfig]:
    tenants, default_tenant = load_tenants(settings)
    enabled = {tid: t for tid, t in tenants.items() if t.enabled}
    if all_tenants:
        return list(enabled.values())
    target_id = tenant_id or default_tenant
    tenant = enabled.get(target_id)
    if tenant is None:
        LOGGER.error("Tenant '%s' no existe o está deshabilitado", target_id)
        return []
    return [tenant]


def cli_entrypoint() -> None:
    parser = argparse.ArgumentParser(description="Ingesta de Markdown a FAISS")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Monitorea el directorio de documentos y reindexa al detectar cambios",
    )
    parser.add_argument("--tenant", default=None, help="Ingesta un tenant específico por id")
    parser.add_argument(
        "--all", action="store_true", dest="all_tenants", help="Ingesta todos los tenants habilitados"
    )
    args = parser.parse_args()

    configure_logging(settings.log_path)

    selected = _select_tenants(args.tenant, args.all_tenants)
    if not selected:
        return

    for tenant in selected:
        stats = ingest_once(tenant)
        if stats:
            LOGGER.info(
                "[%s] Ingesta inicial: %d archivos, %d chunks en %.2fs",
                tenant.id,
                stats.processed_files,
                stats.total_chunks,
                stats.duration_seconds,
            )

    if args.watch:
        watch_documents(selected)


if __name__ == "__main__":
    cli_entrypoint()
