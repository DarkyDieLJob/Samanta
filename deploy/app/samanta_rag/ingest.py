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
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .config import settings
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
    splitter = RecursiveCharacterTextSplitter(
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
        chunks = splitter.split_text(text)
        metadata_entries.append(
            FileMetadata(
                source=str(rel_path),
                hash=content_hash,
                mtime=file_path.stat().st_mtime,
                chunk_count=len(chunks),
            )
        )
        metadata_base = {
            "source": str(rel_path),
            "mtime": file_path.stat().st_mtime,
            "hash": content_hash,
        }
        for idx, chunk in enumerate(chunks):
            metadata = metadata_base | {"chunk_index": idx}
            documents.append(Document(page_content=chunk, metadata=metadata))
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
) -> Optional[FAISS]:
    if not documents:
        LOGGER.warning("No se encontraron documentos para indexar. Se mantiene el índice anterior.")
        return None
    embeddings = OllamaEmbeddings(model=settings.embedding_model_name, base_url=settings.ollama_base_url)
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


def ingest_once() -> Optional[IngestStats]:
    start = time.time()
    documents_dir = settings.documents_path
    if not documents_dir.exists():
        LOGGER.error("El directorio de documentos %s no existe", documents_dir)
        return None
    document_files = collect_markdown_documents(documents_dir)
    documents, metadata_entries = load_documents(document_files, documents_dir)
    LOGGER.info("Recopilados %d documentos y %d chunks", len(document_files), len(documents))

    previous_metadata = load_previous_metadata(settings.vectorstore_path)
    needs_update = metadata_changed(metadata_entries, previous_metadata)
    if not needs_update and settings.vectorstore_path.exists():
        LOGGER.info("No se detectaron cambios en los documentos. Se omite la reindexación.")
        duration = time.time() - start
        return IngestStats(
            processed_files=len(document_files),
            total_chunks=len(documents),
            duration_seconds=duration,
            updated=False,
        )

    vectorstore = build_vectorstore(documents, metadata_entries, settings.vectorstore_path)
    duration = time.time() - start
    return IngestStats(
        processed_files=len(document_files),
        total_chunks=len(documents),
        duration_seconds=duration,
        updated=vectorstore is not None,
    ) if vectorstore else None


def watch_documents() -> None:
    observer = Observer()
    event_handler = MarkdownWatcher(lambda: _safe_ingest())
    observer.schedule(event_handler, str(settings.documents_path), recursive=True)
    observer.start()
    LOGGER.info("Monitoreo de documentos iniciado en %s", settings.documents_path)

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


def _safe_ingest() -> None:
    try:
        stats = ingest_once()
        if stats and stats.updated:
            LOGGER.info(
                "Ingesta completada: %d archivos, %d chunks en %.2fs",
                stats.processed_files,
                stats.total_chunks,
                stats.duration_seconds,
            )
        elif stats:
            LOGGER.info(
                "Ingesta saltada: %d archivos revisados sin cambios relevantes",
                stats.processed_files,
            )
    except Exception:  # noqa: BLE001
        LOGGER.exception("Fallo durante la ingesta")


def cli_entrypoint() -> None:
    parser = argparse.ArgumentParser(description="Ingesta de Markdown a FAISS")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Monitorea el directorio de documentos y reindexa al detectar cambios",
    )
    args = parser.parse_args()

    configure_logging(settings.log_path)

    stats = ingest_once()
    if stats:
        LOGGER.info(
            "Ingesta inicial completada: %d archivos, %d chunks en %.2fs",
            stats.processed_files,
            stats.total_chunks,
            stats.duration_seconds,
        )

    if args.watch:
        watch_documents()


if __name__ == "__main__":
    cli_entrypoint()
