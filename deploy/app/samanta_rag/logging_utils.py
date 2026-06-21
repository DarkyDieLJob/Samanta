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
    """Configura logging en consola más archivo rotativo con formato key=value.

    Si ``log_path`` no se puede crear por falta de permisos (p. ej. ``/logs``
    en desarrollo local), cae a un directorio ``logs`` relativo al CWD. Si
    tampoco se puede crear allí, se loguea solo por consola.
    """

    original_path = log_path
    for attempt_path in (original_path, Path("logs")):
        try:
            attempt_path.mkdir(parents=True, exist_ok=True)
            log_path = attempt_path
            break
        except OSError as exc:
            logging.warning("No se pudo crear %s: %s", attempt_path, exc)
    else:
        logging.warning("No se pudo crear ningún directorio de logs; solo consola")
        log_path = None

    log_file = log_path / "samanta_rag.log" if log_path else None
    formatter = logging.Formatter(_FORMAT)

    handlers = [logging.StreamHandler()]

    if log_file:
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
