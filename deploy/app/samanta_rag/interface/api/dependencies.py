"""Dependencias para la API de Samanta RAG."""

from __future__ import annotations

from typing import Optional

from ...application.query_handler import QueryHandler
from ...config import Settings

_QUERY_HANDLER: Optional[QueryHandler] = None
_SETTINGS: Optional[Settings] = None


def configure_dependencies(handler: QueryHandler, settings: Settings) -> None:
    global _QUERY_HANDLER, _SETTINGS
    _QUERY_HANDLER = handler
    _SETTINGS = settings


def get_query_handler() -> QueryHandler:
    if _QUERY_HANDLER is None:
        raise RuntimeError("QueryHandler no configurado")
    return _QUERY_HANDLER


def get_settings() -> Settings:
    if _SETTINGS is None:
        raise RuntimeError("Settings no configurado")
    return _SETTINGS
