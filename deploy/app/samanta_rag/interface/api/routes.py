"""Rutas HTTP para la API de Samanta RAG."""

from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...application.query_handler import QueryHandler
from .dependencies import (
    get_default_tenant,
    get_query_handler,
    get_settings,
    list_tenants,
)
from ...mcp.registry import load_registry_from_env
from ...mcp.client import MCPClient, MCPClientError, MCPProvider

router = APIRouter()


def _resolve_handler(tenant: Optional[str] = None) -> QueryHandler:
    """Dependencia que resuelve el handler por tenant (?tenant=) o 404."""
    try:
        return get_query_handler(tenant)
    except KeyError:
        raise HTTPException(status_code=404, detail="Tenant desconocido")


class QueryPayload(BaseModel):
    question: str
    tenant: Optional[str] = None
    only_cached: bool = False


class QueryResponseSchema(BaseModel):
    answer: str
    sources: list[str]
    cached: bool = False
    served: bool = True


@router.get("/health", response_model=Dict[str, object])
async def health(handler: QueryHandler = Depends(_resolve_handler)) -> Dict[str, object]:
    summary = handler.summary().to_dict()
    status = "ok" if handler.is_available() else "missing_index"
    registry = handler.mcp_registry_summary()
    metrics = handler.mcp_metrics_snapshot()
    return {
        "status": status,
        "summary": summary,
        "mcp": registry,
        "mcp_metrics": metrics,
    }


@router.post("/api/reload", response_model=Dict[str, str])
async def reload(handler: QueryHandler = Depends(_resolve_handler)) -> Dict[str, str]:
    handler.refresh_vectorstore()
    status = "ok" if handler.is_available() else "missing_index"
    return {"status": status}


@router.get("/api/status", response_model=Dict[str, object])
async def status(handler: QueryHandler = Depends(_resolve_handler)) -> Dict[str, object]:
    summary = handler.summary().to_dict()
    status = "ok" if handler.is_available() else "missing_index"
    settings = get_settings()
    allowed_ips = list(settings.allowed_ips) if settings.allowed_ips else ["*"]
    return {
        "status": status,
        "summary": summary,
        "allowed_ips": allowed_ips,
        "tenants": list_tenants(),
        "default_tenant": get_default_tenant(),
    }


@router.get("/api/mcp/teatro-bar/health", response_model=Dict[str, object])
async def mcp_teatro_bar_health() -> Dict[str, object]:
    """Prueba de conectividad contra teatro-bar.health.ping.

    Devuelve un objeto con { provider, ok, details } y maneja fallbacks de forma segura.
    """
    registry = load_registry_from_env()
    if not registry:
        raise HTTPException(status_code=503, detail="MCP deshabilitado por configuración")
    provider_cfg: Optional[object] = next((p for p in registry.providers if p.name == "teatro-bar"), None)
    if provider_cfg is None:
        raise HTTPException(status_code=404, detail="Proveedor teatro-bar no registrado")
    # map dataclass ProviderConfig -> MCPProvider expected by client
    p = provider_cfg  # type: ignore[assignment]
    provider = MCPProvider(
        name=p.name,  # type: ignore[attr-defined]
        endpoint=p.endpoint,  # type: ignore[attr-defined]
        token_env=p.token_env,  # type: ignore[attr-defined]
        timeout_seconds=p.timeout_seconds,  # type: ignore[attr-defined]
        max_retries=p.max_retries,  # type: ignore[attr-defined]
        preferred=p.preferred,  # type: ignore[attr-defined]
        required=p.required,  # type: ignore[attr-defined]
        tools_whitelist=p.tools,  # type: ignore[attr-defined]
        domains=p.domains,  # type: ignore[attr-defined]
        keywords=p.keywords,  # type: ignore[attr-defined]
    )
    client = MCPClient(provider)
    try:
        resp = await client.health_ping()
        ok = bool(resp.get("status") == "ok")
        return {"provider": provider.name, "ok": ok, "details": resp}
    except MCPClientError as exc:
        # Fallback: no inventar datos, reportar indisponibilidad breve
        return {
            "provider": provider.name,
            "ok": False,
            "details": {"error": str(exc)},
            "message": "Fuera de servicio temporalmente (eventos en vivo: teatro-bar)",
        }


@router.post("/api/query", response_model=QueryResponseSchema)
async def query(payload: QueryPayload) -> QueryResponseSchema:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Pregunta vacía")
    handler = _resolve_handler(payload.tenant)

    # Modo "solo caché": no se invoca el LLM. Si no hay respuesta cacheada,
    # se indica served=False para que el llamador decida (p. ej. aplicar cupo).
    if payload.only_cached:
        cached = handler.try_cached(question)
        if cached is None:
            return QueryResponseSchema(answer="", sources=[], cached=False, served=False)
        return QueryResponseSchema(
            answer=cached.answer, sources=cached.sources, cached=True, served=True
        )

    try:
        result = handler.run(question)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return QueryResponseSchema(
        answer=result.answer, sources=result.sources, cached=result.cached, served=True
    )
