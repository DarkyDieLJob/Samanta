"""Descubrimiento y registro en memoria de herramientas MCP."""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple, TypeVar

from .client import MCPClient, MCPClientError, MCPProvider
from .registry import ProviderConfig, RegistryConfig

LOGGER = logging.getLogger(__name__)
_T = TypeVar("_T")


def _run_coro_blocking(factory: Callable[[], Awaitable[_T]]) -> _T:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result: Dict[str, _T] = {}
    error: Dict[str, BaseException] = {}

    def _runner() -> None:
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            result["value"] = new_loop.run_until_complete(factory())
        except BaseException as exc:  # noqa: BLE001
            error["error"] = exc
        finally:
            new_loop.close()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if error:
        raise error["error"]
    return result["value"]


@dataclass(frozen=True)
class RegisteredTool:
    """Representa una tool MCP registrada con nombre calificado."""

    provider: MCPProvider
    tool_name: str
    fq_name: str
    description: str
    metadata: Dict[str, Any]
    domains: Tuple[str, ...] = ()
    keywords: Tuple[str, ...] = ()
    preferred: bool = False
    required: bool = False


class MCPToolRegistry:
    """Estructura runtime que expone herramientas MCP descubribles."""

    def __init__(self, tools: Sequence[RegisteredTool]) -> None:
        self._tools_by_name: Dict[str, RegisteredTool] = {tool.fq_name: tool for tool in tools}
        self._tools_by_provider: Dict[str, List[RegisteredTool]] = {}
        for tool in tools:
            self._tools_by_provider.setdefault(tool.provider.name, []).append(tool)

    def get(self, fq_name: str) -> Optional[RegisteredTool]:
        return self._tools_by_name.get(fq_name)

    def tools_for_provider(self, provider_name: str) -> List[RegisteredTool]:
        return list(self._tools_by_provider.get(provider_name, ()))

    def all_tools(self) -> List[RegisteredTool]:
        return list(self._tools_by_name.values())

    def summary(self) -> Dict[str, object]:
        return {
            "providers": len(self._tools_by_provider),
            "tools": len(self._tools_by_name),
        }


def _provider_from_config(cfg: ProviderConfig) -> MCPProvider:
    return MCPProvider(
        name=cfg.name,
        endpoint=cfg.endpoint,
        token_env=cfg.token_env,
        timeout_seconds=cfg.timeout_seconds,
        max_retries=cfg.max_retries,
        preferred=cfg.preferred,
        required=cfg.required,
        tools_whitelist=cfg.tools,
        domains=cfg.domains,
        keywords=cfg.keywords,
    )


async def _discover_provider(cfg: ProviderConfig) -> List[RegisteredTool]:
    provider = _provider_from_config(cfg)
    client = MCPClient(provider)
    tools: List[RegisteredTool] = []
    try:
        discovered = await client.list_tools()
    except MCPClientError as exc:
        raise MCPClientError(f"No se pudo listar herramientas de {provider.name}: {exc}") from exc

    allowed = set(cfg.tools)
    for tool_info in discovered:
        if tool_info.name not in allowed:
            continue
        tools.append(
            RegisteredTool(
                provider=provider,
                tool_name=tool_info.name,
                fq_name=f"{provider.name}.{tool_info.name}",
                description=tool_info.description,
                metadata=tool_info.metadata,
                domains=cfg.domains,
                keywords=cfg.keywords,
                preferred=cfg.preferred,
                required=cfg.required,
            )
        )

    missing = allowed - {tool.tool_name for tool in tools}
    if missing:
        LOGGER.warning(
            "Proveedor %s no expuso las herramientas declaradas: %s",
            provider.name,
            ", ".join(sorted(missing)),
        )
    return tools


def build_tool_registry(config: RegistryConfig) -> MCPToolRegistry:
    """Construye el registro runtime realizando descubrimiento vía MCP."""

    tools: List[RegisteredTool] = []
    for provider_cfg in config.providers:
        try:
            provider_tools = _run_coro_blocking(lambda cfg=provider_cfg: _discover_provider(cfg))
        except MCPClientError as exc:
            LOGGER.error("Fallo descubriendo tools de %s: %s", provider_cfg.name, exc)
            continue
        tools.extend(provider_tools)
    return MCPToolRegistry(tools)
