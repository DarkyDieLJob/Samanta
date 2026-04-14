"""Rutas HTTP para la API de Samanta RAG."""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...application.query_handler import QueryHandler
from .dependencies import get_query_handler, get_settings

router = APIRouter()


class QueryPayload(BaseModel):
    question: str


class QueryResponseSchema(BaseModel):
    answer: str
    sources: list[str]


@router.get("/health", response_model=Dict[str, object])
async def health(handler: QueryHandler = Depends(get_query_handler)) -> Dict[str, object]:
    summary = handler.summary().to_dict()
    status = "ok" if handler.is_available() else "missing_index"
    return {"status": status, "summary": summary}


@router.post("/api/reload", response_model=Dict[str, str])
async def reload(handler: QueryHandler = Depends(get_query_handler)) -> Dict[str, str]:
    handler.refresh_vectorstore()
    status = "ok" if handler.is_available() else "missing_index"
    return {"status": status}


@router.get("/api/status", response_model=Dict[str, object])
async def status(handler: QueryHandler = Depends(get_query_handler)) -> Dict[str, object]:
    summary = handler.summary().to_dict()
    status = "ok" if handler.is_available() else "missing_index"
    settings = get_settings()
    allowed_ips = list(settings.allowed_ips) if settings.allowed_ips else ["*"]
    return {"status": status, "summary": summary, "allowed_ips": allowed_ips}


@router.post("/api/query", response_model=QueryResponseSchema)
async def query(payload: QueryPayload, handler: QueryHandler = Depends(get_query_handler)) -> QueryResponseSchema:
    if not payload.question.strip():
        raise HTTPException(status_code=422, detail="Pregunta vacía")
    try:
        result = handler.run(payload.question.strip())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return QueryResponseSchema(answer=result.answer, sources=result.sources)
