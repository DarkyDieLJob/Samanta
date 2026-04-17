"""Configuración de logging para el agente RAG."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5
_FORMAT = "ts=%(asctime)s level=%(levelname)s logger=%(name)s msg=\"%(message)s\""


def configure_logging(log_path: Path, *, level: int = logging.INFO) -> None:
    """Configura logging en consola más archivo rotativo con formato key=value."""

    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "samanta_rag.log"
    formatter = logging.Formatter(_FORMAT)

    handlers = [logging.StreamHandler()]

    try:
        file_handler: Optional[RotatingFileHandler] = RotatingFileHandler(
            log_file,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
        )
    except OSError:
        file_handler = None

    if file_handler:
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    handlers[0].setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()
    for handler in handlers:
        root_logger.addHandler(handler)
