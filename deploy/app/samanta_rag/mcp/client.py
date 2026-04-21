"""Cliente MCP genérico usando el SDK oficial vía WebSocket (WSS).

Responsabilidades:
- Crear sesiones MCP reales (initialize -> call_tool/list_tools) respetando el
  protocolo del SDK oficial.
- Manejar timeouts y reintentos configurables por proveedor.
- Inyectar automáticamente credenciales (`token`, `token_internal`) en los
  argumentos esperados por el servidor.
- Exponer operaciones de descubrimiento (`list_tools`) y ejecución
  (`call_tool`/`health_ping`).
"""

from __future__ import annotations

import asyncio
import logging
import os
import ssl
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, TypeVar

try:  # pragma: no cover - la disponibilidad depende del entorno de despliegue
    from mcp.client.session import ClientSession  # type: ignore
    from mcp.client.websocket import websocket_client  # type: ignore
except Exception:  # pragma: no cover - mostramos mensaje amigable más adelante
    ClientSession = None  # type: ignore
    websocket_client = None  # type: ignore


LOGGER = logging.getLogger(__name__)
_SDK_INSTALL_HINT = "pip install 'mcp>=1.2.0'"
_ReturnType = TypeVar("_ReturnType")


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


def _build_ssl_context() -> Optional[ssl.SSLContext]:
    """Construye contexto SSL opcional en base a MCP_CA_BUNDLE."""

    custom_ca = os.getenv("MCP_CA_BUNDLE", "").strip()
    if not custom_ca:
        return None
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=custom_ca)
    return context


def _normalize_payload(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        data = obj.model_dump()  # type: ignore[call-arg]
        if isinstance(data, dict):
            return data
    if hasattr(obj, "dict"):
        data = obj.dict()  # type: ignore[call-arg]
        if isinstance(data, dict):
            return data
    raise MCPClientError("Respuesta inválida del MCP (se esperaba objeto JSON)")


def _ensure_sdk_available() -> None:
    if ClientSession is None or websocket_client is None:
        raise MCPClientError(
            "El SDK cliente de MCP no está instalado. Ejecuta "
            f"{_SDK_INSTALL_HINT}" 
        )


class MCPClient:
    """Cliente WebSocket asincrónico con retries y timeouts configurables."""

    def __init__(self, provider: MCPProvider, *, request_id: Optional[str] = None) -> None:
        self._provider = provider
        self._timeout = max(1, provider.timeout_seconds)
        self._max_retries = max(0, provider.max_retries)
        self._request_id = request_id or str(uuid.uuid4())
        self._ssl_context = _build_ssl_context()

    async def list_tools(self) -> List[MCPToolInfo]:
        async def _operation(session: ClientSession) -> List[MCPToolInfo]:
            response = await session.list_tools()  # type: ignore[attr-defined]
            payload = _normalize_payload(response)
            tools_raw: Any = payload.get("tools")
            if tools_raw is None and hasattr(response, "tools"):
                tools_raw = []
                for item in getattr(response, "tools"):
                    if hasattr(item, "model_dump"):
                        tools_raw.append(item.model_dump())  # type: ignore[call-arg]
                    elif hasattr(item, "dict"):
                        tools_raw.append(item.dict())  # type: ignore[call-arg]
                    else:
                        tools_raw.append(item)
            if not isinstance(tools_raw, list):
                raise MCPClientError("Respuesta inválida de list_tools (se esperaba lista)")
            tools: List[MCPToolInfo] = []
            for item in tools_raw:
                if isinstance(item, dict):
                    tool = MCPToolInfo.from_raw(item)
                    if tool:
                        tools.append(tool)
            return tools

        return await self._run_with_retry(_operation)

    async def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        async def _operation(session: ClientSession) -> Dict[str, Any]:
            args: Dict[str, Any] = dict(arguments or {})
            token = self._provider.resolve_token()
            if token:
                args.setdefault("token", token)
                args.setdefault("token_internal", token)
            result = await session.call_tool(tool_name, arguments=args)  # type: ignore[attr-defined]
            payload = _normalize_payload(result)
            payload.setdefault("retries", 0)
            return payload

        return await self._run_with_retry(_operation)

    async def health_ping(self) -> Dict[str, Any]:
        return await self.call_tool("health.ping", {})

    async def _run_with_retry(self, operation: Callable[[ClientSession], Awaitable[_ReturnType]]) -> _ReturnType:
        _ensure_sdk_available()
        last_exc: Optional[BaseException] = None
        for attempt in range(self._max_retries + 1):
            try:
                return await self._run_once(operation)
            except (
                asyncio.TimeoutError,
                MCPClientError,
                OSError,
                RuntimeError,
            ) as exc:
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

    async def _run_once(self, operation: Callable[[ClientSession], Awaitable[_ReturnType]]) -> _ReturnType:
        connect_kwargs: Dict[str, Any] = {}
        if self._ssl_context is not None:
            connect_kwargs["ssl"] = self._ssl_context

        async with websocket_client(self._provider.endpoint, **connect_kwargs) as (read, write):  # type: ignore[arg-type]
            async with ClientSession(read, write) as session:  # type: ignore[call-arg]
                await asyncio.wait_for(session.initialize(), timeout=self._timeout)
                return await asyncio.wait_for(operation(session), timeout=self._timeout)
