"""Middlewares para la API de Samanta RAG."""

from __future__ import annotations

import logging
from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

LOGGER = logging.getLogger(__name__)


class IPAllowlistMiddleware(BaseHTTPMiddleware):
    """Permite acceso únicamente desde IPs autorizadas."""

    def __init__(self, app, allowed_ips: Iterable[str]) -> None:
        super().__init__(app)
        self._allowed_ips = tuple(allowed_ips)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if self._allowed_ips:
            client_host = request.client.host if request.client else None
            if client_host not in self._allowed_ips:
                LOGGER.warning("Acceso bloqueado para IP no permitida: %s", client_host)
                return JSONResponse(status_code=403, content={"detail": "IP no autorizada"})
        return await call_next(request)
