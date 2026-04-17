"""Carga y validación del Registro de Proveedores MCP desde variables de entorno.

- Origen de configuración: MCP_REGISTRY_JSON (contenido JSON) o MCP_REGISTRY_PATH (ruta a archivo JSON).
- Se validan tokens por proveedor (token_env debe existir en el entorno).
- Se aplican defaults: timeout_seconds, max_retries.
- Se soportan campos opcionales por proveedor: domains, keywords.
- Se exige WSS en endpoint (wss://) y no se exponen tokens en logs/errores.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


class MCPRegistryError(Exception):
    pass


@dataclass(frozen=True)
class Defaults:
    timeout_seconds: int = 5
    max_retries: int = 1


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    endpoint: str
    token_env: str
    timeout_seconds: int
    max_retries: int
    preferred: bool
    required: bool
    tools: Tuple[str, ...]
    # Opcionales para ruteo por intención
    domains: Tuple[str, ...] = ()
    keywords: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RegistryConfig:
    providers: Tuple[ProviderConfig, ...]
    defaults: Defaults


def _ensure_wss(endpoint: str) -> None:
    if not endpoint.lower().startswith("wss://"):
        raise MCPRegistryError("El endpoint de MCP debe usar WSS (wss://)")


def _require_env_var(var_name: str) -> None:
    if not var_name or not os.getenv(var_name, "").strip():
        raise MCPRegistryError(
            f"La variable de entorno del token '{var_name}' no está definida o está vacía"
        )


def _coerce_tuple_str_list(value: Optional[List[str]]) -> Tuple[str, ...]:
    if not value:
        return ()
    return tuple(str(v).strip() for v in value if str(v).strip())


def _parse_defaults(obj: dict) -> Defaults:
    raw = obj or {}
    return Defaults(
        timeout_seconds=int(raw.get("timeout_seconds", Defaults.timeout_seconds)),
        max_retries=int(raw.get("max_retries", Defaults.max_retries)),
    )


def _parse_provider(obj: dict, defaults: Defaults) -> ProviderConfig:
    try:
        name = str(obj["name"]).strip()
        # Permitir endpoint por literal o por variable de entorno usando 'endpoint_env'
        raw_endpoint = str(obj.get("endpoint", "")).strip()
        endpoint_env = str(obj.get("endpoint_env", "")).strip()
        token_env = str(obj["token_env"]).strip()
    except KeyError as e:
        raise MCPRegistryError(f"Proveedor mal definido, falta la clave: {e}") from e

    # Resolver endpoint según precedencia: endpoint_env > endpoint literal
    if endpoint_env:
        resolved = os.getenv(endpoint_env, "").strip()
        if not resolved:
            raise MCPRegistryError(
                f"La variable de entorno del endpoint '{endpoint_env}' no está definida o está vacía"
            )
        endpoint = resolved
    else:
        endpoint = raw_endpoint

    _ensure_wss(endpoint)
    _require_env_var(token_env)

    timeout_seconds = int(obj.get("timeout_seconds", defaults.timeout_seconds))
    max_retries = int(obj.get("max_retries", defaults.max_retries))
    preferred = bool(obj.get("preferred", False))
    required = bool(obj.get("required", False))

    tools_list = obj.get("tools", [])
    if not isinstance(tools_list, list) or not tools_list:
        raise MCPRegistryError("Cada proveedor debe definir una lista no vacía de 'tools'")
    tools: Tuple[str, ...] = _coerce_tuple_str_list(tools_list)

    domains = _coerce_tuple_str_list(obj.get("domains"))
    keywords = _coerce_tuple_str_list(obj.get("keywords"))

    return ProviderConfig(
        name=name,
        endpoint=endpoint,
        token_env=token_env,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        preferred=preferred,
        required=required,
        tools=tools,
        domains=domains,
        keywords=keywords,
    )


def _parse_registry(data: dict) -> RegistryConfig:
    if not isinstance(data, dict):
        raise MCPRegistryError("El JSON de registro MCP debe ser un objeto JSON")

    defaults = _parse_defaults(data.get("defaults") or {})

    providers_raw = data.get("providers")
    if not isinstance(providers_raw, list) or not providers_raw:
        raise MCPRegistryError("'providers' debe ser una lista no vacía")

    providers = tuple(_parse_provider(p, defaults) for p in providers_raw)
    # Validar unicidad de nombres
    names = [p.name for p in providers]
    if len(set(names)) != len(names):
        raise MCPRegistryError("Los nombres de proveedores deben ser únicos")

    return RegistryConfig(providers=providers, defaults=defaults)


def load_registry_from_env() -> Optional[RegistryConfig]:
    """Carga el registro MCP desde MCP_REGISTRY_JSON o MCP_REGISTRY_PATH.

    Precedencia: MCP_REGISTRY_JSON > MCP_REGISTRY_PATH. Si ninguna está definida,
    retorna None (feature deshabilitada por config).
    """
    raw_json = os.getenv("MCP_REGISTRY_JSON", "").strip()
    if raw_json:
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as e:
            raise MCPRegistryError("MCP_REGISTRY_JSON no es un JSON válido") from e
        return _parse_registry(data)

    path = os.getenv("MCP_REGISTRY_PATH", "").strip()
    if path:
        p = Path(path)
        if not p.exists() or not p.is_file():
            raise MCPRegistryError(f"MCP_REGISTRY_PATH no existe o no es un archivo: {p}")
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise MCPRegistryError("El archivo MCP_REGISTRY_PATH no contiene JSON válido") from e
        return _parse_registry(data)

    return None
