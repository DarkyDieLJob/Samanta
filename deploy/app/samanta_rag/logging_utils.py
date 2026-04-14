"""Configuración de logging para el agente RAG."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


def configure_logging(log_path: Path, *, level: int = logging.INFO, max_bytes: int = 5 * 1024 * 1024) -> None:
    """Configura logging con salida a consola y archivo rotativo."""
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "samanta_rag.log"

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    handlers = [logging.StreamHandler()]

    try:
        file_handler: Optional[RotatingFileHandler] = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=3)
    except OSError:
        file_handler = None

    if file_handler:
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    stream_handler = handlers[0]
    stream_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()
    for handler in handlers:
        root_logger.addHandler(handler)
