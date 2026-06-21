"""Tests de la API multi-tenant sin tocar LLMs ni bases vectoriales reales."""

from __future__ import annotations

from typing import List

from fastapi import FastAPI
from fastapi.testclient import TestClient

from samanta_rag.application.query_handler import QueryHandler
from samanta_rag.config import Settings, get_settings
from samanta_rag.domain.entities import QueryResult, VectorStoreSummary
from samanta_rag.interface.api.dependencies import configure_dependencies
from samanta_rag.interface.api import routes


class FakeQueryHandler(QueryHandler):
    """Handler fake que devuelve respuestas diferenciadas por tenant."""

    def __init__(self, tenant: str) -> None:
        # No necesitamos query_service real para estos tests.
        self._tenant = tenant
        self.refreshed = False

    def run(self, question: str) -> QueryResult:
        return QueryResult(
            answer=f"Respuesta de {self._tenant}: {question}",
            sources=[f"{self._tenant}/doc1.md"],
        )

    def summary(self) -> VectorStoreSummary:
        return VectorStoreSummary(total_files=3, total_chunks=12, last_updated=None)

    def is_available(self) -> bool:
        return True

    def refresh_vectorstore(self) -> None:
        self.refreshed = True

    def mcp_registry_summary(self) -> dict[str, object]:
        return {"enabled": True, "tenant": self._tenant}

    def mcp_metrics_snapshot(self) -> list[dict[str, object]]:
        return []


def _build_client(handlers: dict[str, QueryHandler], default_tenant: str) -> TestClient:
    app = FastAPI()
    app.include_router(routes.router)
    configure_dependencies(handlers, default_tenant, get_settings())
    return TestClient(app)


def test_query_unknown_tenant_returns_404() -> None:
    """Consultar un tenant inexistente debe devolver 404."""
    client = _build_client({"teatro": FakeQueryHandler("teatro")}, "teatro")
    response = client.post("/api/query", json={"question": "hola", "tenant": "inexistente"})
    assert response.status_code == 404
    assert response.json()["detail"] == "Tenant desconocido"


def test_query_without_tenant_uses_default() -> None:
    """Sin tenant, la API debe usar el default."""
    client = _build_client(
        {"teatro": FakeQueryHandler("teatro"), "portfolio": FakeQueryHandler("portfolio")},
        "portfolio",
    )
    response = client.post("/api/query", json={"question": "¿Quién es?"})
    assert response.status_code == 200
    data = response.json()
    assert data["answer"].startswith("Respuesta de portfolio")
    assert data["sources"] == ["portfolio/doc1.md"]


def test_query_tenant_isolation() -> None:
    """Las respuestas deben provenir del tenant solicitado, no mezclarse."""
    client = _build_client(
        {"teatro": FakeQueryHandler("teatro"), "portfolio": FakeQueryHandler("portfolio")},
        "teatro",
    )
    portfolio_resp = client.post("/api/query", json={"question": "¿Quién es?", "tenant": "portfolio"})
    teatro_resp = client.post("/api/query", json={"question": "¿Eventos?", "tenant": "teatro"})

    assert portfolio_resp.status_code == 200
    assert teatro_resp.status_code == 200

    assert portfolio_resp.json()["sources"] == ["portfolio/doc1.md"]
    assert teatro_resp.json()["sources"] == ["teatro/doc1.md"]
    assert portfolio_resp.json()["answer"].startswith("Respuesta de portfolio")
    assert teatro_resp.json()["answer"].startswith("Respuesta de teatro")


def test_status_lists_tenants_and_default() -> None:
    """GET /api/status debe listar tenants y el default."""
    client = _build_client(
        {"teatro": FakeQueryHandler("teatro"), "portfolio": FakeQueryHandler("portfolio")},
        "portfolio",
    )
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert sorted(data["tenants"]) == ["portfolio", "teatro"]
    assert data["default_tenant"] == "portfolio"
    assert data["status"] == "ok"


def test_health_can_resolve_specific_tenant() -> None:
    """GET /health debe respetar ?tenant=."""
    client = _build_client(
        {"teatro": FakeQueryHandler("teatro"), "portfolio": FakeQueryHandler("portfolio")},
        "portfolio",
    )
    response = client.get("/health?tenant=teatro")
    assert response.status_code == 200
    data = response.json()
    assert data["mcp"]["tenant"] == "teatro"


def test_reload_refreshes_specific_tenant() -> None:
    """POST /api/reload debe refrescar el vectorstore del tenant."""
    teatro = FakeQueryHandler("teatro")
    portfolio = FakeQueryHandler("portfolio")
    client = _build_client({"teatro": teatro, "portfolio": portfolio}, "portfolio")
    response = client.post("/api/reload?tenant=teatro")
    assert response.status_code == 200
    assert teatro.refreshed is True
    assert portfolio.refreshed is False


def test_query_empty_question_returns_422() -> None:
    """Pregunta vacía debe devolver 422."""
    client = _build_client({"teatro": FakeQueryHandler("teatro")}, "teatro")
    response = client.post("/api/query", json={"question": "  ", "tenant": "teatro"})
    assert response.status_code == 422
