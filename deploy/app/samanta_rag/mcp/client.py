"""Cliente MCP por WebSocket con envoltorios síncronos.

Soporta las herramientas del proveedor `teatro-bar`:
- events.this_week, events.past, events.future, events.by_id
- health.ping

Nota: Usa `asyncio.run` internamente para simplificar la integración
con el pipeline síncrono actual.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import websockets


@dataclass(frozen=True)
class MCPProvider:
    name: str
    endpoint: str
    token_env: str
    timeout_seconds: int = 5
    max_retries: int = 1


class MCPClientError(Exception):
    pass


class MCPClient:
    def __init__(self, provider: MCPProvider) -> None:
        self._provider = provider
        token = os.getenv(provider.token_env, "").strip()
        if not token:
            raise MCPClientError(f"Token no definido en env: {provider.token_env}")
        self._auth_header = ("Authorization", f"Bearer {token}")

    def _run_ws(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        async def _call() -> Dict[str, Any]:
            headers = [self._auth_header]
            async with websockets.connect(self._provider.endpoint, extra_headers=headers) as ws:  # type: ignore[arg-type]
                await ws.send(json.dumps(payload))
                raw = await asyncio.wait_for(ws.recv(), timeout=self._provider.timeout_seconds)
                return json.loads(raw)

        last_exc: Optional[BaseException] = None
        attempts = self._provider.max_retries + 1
        for attempt in range(attempts):
            try:
                return asyncio.run(asyncio.wait_for(_call(), timeout=self._provider.timeout_seconds + 1))
            except Exception as exc:  # noqa: BLE001 - surface upstream errors as single message
                last_exc = exc
                if attempt < attempts - 1:
                    # backoff exponencial corto
                    time.sleep(0.25 * (2**attempt))
        raise MCPClientError(f"Fallo de MCP WSS en {self._provider.name}: {last_exc}")

    # Métodos de conveniencia
    def health_ping(self) -> Dict[str, Any]:
        return self._run_ws({"tool": "health.ping", "params": {}})

    def events_this_week(self, *, limit: int = 20, offset: int = 0, **kwargs: Any) -> Dict[str, Any]:
        limit = max(1, min(limit, 100))
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        params.update(kwargs)
        return self._run_ws({"tool": "events.this_week", "params": params})

    def events_past(self, *, limit: int = 20, offset: int = 0, since: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        limit = max(1, min(limit, 100))
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if since:
            params["since"] = since
        params.update(kwargs)
        return self._run_ws({"tool": "events.past", "params": params})

    def events_future(self, *, limit: int = 20, offset: int = 0, until: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        limit = max(1, min(limit, 100))
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if until:
            params["until"] = until
        params.update(kwargs)
        return self._run_ws({"tool": "events.future", "params": params})

    def events_by_id(self, *, id: int) -> Dict[str, Any]:  # noqa: A002 - API pública del servidor
        return self._run_ws({"tool": "events.by_id", "params": {"id": id}})
