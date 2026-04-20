"""Cliente MCP genérico sobre WebSocket (WSS) con autenticación Bearer.

Responsabilidades:
- Crear conexiones TLS (verificando certificado) y adjuntar cabeceras estándar.
- Manejar timeouts y reintentos configurables por proveedor.
- Exponer operaciones para descubrir herramientas (`list_tools`) y ejecutar
  herramientas (`call_tool`/`health_ping`).
- Proveer metadatos básicos de las herramientas remotas.

Contrato de payloads:
- `list_tools`: envía `{"type": "list_tools"}` y espera `{ "tools": [...] }`.
- `call_tool`: envía `{"type": "call_tool", "tool": "name", "params": {...}}`.
  (Se incluyen campos duplicados para compatibilidad hacia atrás.)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import aiohttp


LOGGER = logging.getLogger(__name__)
_DEFAULT_USER_AGENT = "Samanta-RAG/0.2.0"


class MCPClientError(RuntimeError):
    """Errores de red/protocolo con proveedores MCP."""


@dataclass(frozen=True)
class MCPProvider:
    name: str
    endpoint: str
    token_env: str
    timeout_seconds: int = 5
    max_retries: int = 1
    preferred: bool = False
    required: bool = False
    tools_whitelist: Tuple[str, ...] = ()
    domains: Tuple[str, ...] = ()
    keywords: Tuple[str, ...] = ()

    def resolve_token(self) -> str:
        token = os.getenv(self.token_env, "").strip()
        if not token:
            raise MCPClientError(
                f"Token no definido para proveedor '{self.name}'. Esperaba {self.token_env}"
            )
        return token


@dataclass(frozen=True)
class MCPToolInfo:
    name: str
    description: str = ""
    input_schema: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> Optional["MCPToolInfo"]:
        name = str(raw.get("name", "")).strip()
        if not name:
            return None
        description = str(raw.get("description", "") or "")
        input_schema = raw.get("input_schema")
        if input_schema is not None and not isinstance(input_schema, dict):
            input_schema = None
        return cls(name=name, description=description, input_schema=input_schema, metadata=raw)


def _build_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    custom_ca = os.getenv("MCP_CA_BUNDLE", "").strip()
    if custom_ca:
        context.load_verify_locations(cafile=custom_ca)
    return context


def _ensure_dict(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise MCPClientError("Respuesta inválida del MCP (se esperaba objeto JSON)")
    return payload


class MCPClient:
    """Cliente WebSocket asincrónico con retries y timeouts configurables."""

    def __init__(self, provider: MCPProvider, *, request_id: Optional[str] = None) -> None:
        self._provider = provider
        self._timeout = max(1, provider.timeout_seconds)
        self._max_retries = max(0, provider.max_retries)
        self._request_id = request_id or str(uuid.uuid4())
        # SSL context (CA del sistema o CA personalizada si MCP_CA_BUNDLE está definida)
        self._ssl_context = _build_ssl_context()

    async def list_tools(self) -> List[MCPToolInfo]:
        response = await self._send_with_retry({"type": "list_tools", "request_id": self._request_id})
        tools_raw = response.get("tools", [])
        if not isinstance(tools_raw, list):
            raise MCPClientError("Respuesta inválida de list_tools (se esperaba lista)")
        tools: List[MCPToolInfo] = []
        for item in tools_raw:
            if isinstance(item, dict):
                tool = MCPToolInfo.from_raw(item)
                if tool:
                    tools.append(tool)
        return tools

    async def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {
            "type": "call_tool",
            "tool": tool_name,
            "tool_name": tool_name,
            "params": arguments or {},
            "arguments": arguments or {},
            "request_id": self._request_id,
        }
        return await self._send_with_retry(payload)

    async def health_ping(self) -> Dict[str, Any]:
        return await self.call_tool("health.ping", {})

    async def _send_with_retry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        last_exc: Optional[BaseException] = None
        for attempt in range(self._max_retries + 1):
            try:
                return await self._send_once(payload)
            except (asyncio.TimeoutError, aiohttp.ClientError, MCPClientError, json.JSONDecodeError, OSError) as exc:
                last_exc = exc
                if attempt >= self._max_retries:
                    break
                backoff = min(0.5 * (2**attempt), 2.0)
                LOGGER.warning(
                    "Fallo MCP %s (intento %s/%s): %s",
                    self._provider.name,
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                )
                await asyncio.sleep(backoff)
        raise MCPClientError(f"Fallo de MCP WSS en {self._provider.name}") from last_exc

    async def _send_once(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._provider.resolve_token()}",
            "User-Agent": _DEFAULT_USER_AGENT,
            "X-Request-ID": self._request_id,
        }
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.ws_connect(self._provider.endpoint, headers=headers, ssl=self._ssl_context, autoping=True) as ws:
                await ws.send_str(json.dumps(payload))
                msg = await ws.receive(timeout=self._timeout)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    raw = msg.data
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    raw = msg.data.decode("utf-8", errors="replace")
                else:
                    raise MCPClientError(f"Respuesta WS inesperada: {msg.type}")
        data = json.loads(raw)
        return _ensure_dict(data)
