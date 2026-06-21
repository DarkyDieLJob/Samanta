"""Dependencias para la API de Samanta RAG."""

from __future__ import annotations

from typing import Dict, List, Optional

from ...application.query_handler import QueryHandler
from ...config import Settings

_HANDLERS: Dict[str, QueryHandler] = {}
_DEFAULT_TENANT: str = "default"
_SETTINGS: Optional[Settings] = None


def configure_dependencies(
    handlers: Dict[str, QueryHandler], default_tenant: str, settings: Settings
) -> None:
    global _HANDLERS, _DEFAULT_TENANT, _SETTINGS
    _HANDLERS = dict(handlers)
    _DEFAULT_TENANT = default_tenant
    _SETTINGS = settings


def get_query_handler(tenant: Optional[str] = None) -> QueryHandler:
    """Resuelve el handler de un tenant. Lanza KeyError si no existe."""
    if not _HANDLERS:
        raise RuntimeError("Handlers no configurados")
    key = tenant or _DEFAULT_TENANT
    handler = _HANDLERS.get(key)
    if handler is None:
        raise KeyError(key)
    return handler


def list_tenants() -> List[str]:
    return list(_HANDLERS.keys())


def get_default_tenant() -> str:
    return _DEFAULT_TENANT


def get_settings() -> Settings:
    if _SETTINGS is None:
        raise RuntimeError("Settings no configurado")
    return _SETTINGS
