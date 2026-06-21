"""Inicializa dependencias y contenedores de Samanta RAG."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional

from langchain_core.prompts import ChatPromptTemplate

from .application.answer_cache import AnswerCache
from .application.query_handler import QueryHandler
from .config import Settings, TenantConfig, load_tenants, settings
from .domain.services import QueryService
from .infrastructure.llm.ollama_adapter import OllamaChatModel, OpenAIChatModel
from .infrastructure.vectorstore.embeddings import build_embeddings
from .infrastructure.vectorstore.faiss_adapter import FAISSVectorStoreAdapter
from .mcp.client import MCPClientError
from .mcp.registry import (
    MCPRegistryError,
    RegistryConfig,
    load_registry_from_env,
    load_registry_from_path,
)
from .mcp.tool_registry import build_tool_registry
from .mcp.router import MCPRouter

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppContainer:
    settings: Settings
    handlers: Dict[str, QueryHandler]
    default_tenant: str
    tenants: Dict[str, TenantConfig]

    @property
    def query_handler(self) -> QueryHandler:
        """Handler del tenant por defecto (retrocompatibilidad con UI/legacy)."""
        return self.handlers[self.default_tenant]


def _resolve_registry(tenant: TenantConfig) -> Optional[RegistryConfig]:
    """Resuelve el registro MCP de un tenant.

    - `mcp_registry_path` definido: carga desde ese archivo.
    - `mcp_from_env` (solo tenant default): carga desde variables de entorno.
    - en otro caso: MCP desactivado.
    """
    try:
        if tenant.mcp_registry_path is not None:
            return load_registry_from_path(tenant.mcp_registry_path)
        if tenant.mcp_from_env:
            return load_registry_from_env()
    except MCPRegistryError as exc:
        LOGGER.warning("Registro MCP inválido para tenant '%s': %s", tenant.id, exc)
    return None


def build_handler(tenant: TenantConfig, app_settings: Settings) -> QueryHandler:
    """Construye un QueryHandler aislado para un tenant."""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", tenant.system_prompt),
            ("human", "Pregunta: {question}\n\nContexto:\n{context}"),
        ]
    )
    vectorstore_adapter = FAISSVectorStoreAdapter(
        tenant.vectorstore_path,
        embedding_model_name=tenant.embedding_model_name,
        base_url=app_settings.ollama_base_url,
        embedding_provider=tenant.embedding_provider,
        openai_api_key=app_settings.openai_api_key,
    )
    if tenant.llm_provider == "openai" and app_settings.openai_api_key:
        chat_model = OpenAIChatModel(
            model_name=tenant.model_name,
            temperature=tenant.temperature,
            prompt=prompt,
            api_key=app_settings.openai_api_key,
        )
    else:
        chat_model = OllamaChatModel(
            model_name=tenant.model_name,
            temperature=tenant.temperature,
            base_url=app_settings.ollama_base_url,
            prompt=prompt,
        )
    query_service = QueryService(
        vectorstore=vectorstore_adapter, chat_model=chat_model, top_k=tenant.retrieval_k
    )
    query_handler = QueryHandler(
        query_service=query_service, fallback_top_k=app_settings.rag_faiss_topk
    )

    registry_config = _resolve_registry(tenant)
    if registry_config:
        try:
            tool_registry = build_tool_registry(registry_config)
        except MCPClientError as exc:
            LOGGER.error("No se pudo descubrir herramientas MCP del tenant '%s': %s", tenant.id, exc)
        else:
            query_handler.mcp_router = MCPRouter(tool_registry, chat_model)

    # Caché de respuestas (FAQ precalculadas + aprendizaje). Vive fuera del
    # subdirectorio del vectorstore para sobrevivir a los reingest. El matching
    # semántico se desactiva cuando hay MCP, porque una variante semántica
    # podría corresponder a una consulta de datos en vivo (no cacheable).
    if app_settings.answer_cache_enabled:
        cache_file = tenant.vectorstore_path.parent / "_answer_cache" / f"{tenant.id}.json"
        query_handler.answer_cache = AnswerCache(
            tenant_id=tenant.id,
            cache_file=cache_file,
            vectorstore_path=tenant.vectorstore_path,
            faq_questions=tenant.example_questions,
            faq_answers=tenant.faq_answers or None,
            embedder_factory=lambda: build_embeddings(
                provider=tenant.embedding_provider,
                model_name=tenant.embedding_model_name,
                ollama_base_url=app_settings.ollama_base_url,
                openai_api_key=app_settings.openai_api_key,
            ),
            semantic_enabled=query_handler.mcp_router is None,
            sim_threshold=app_settings.answer_cache_sim_threshold,
            promote_after=app_settings.answer_cache_promote_after,
            max_entries=app_settings.answer_cache_max_entries,
            max_observations=app_settings.answer_cache_max_observations,
        )

    return query_handler


def create_container() -> AppContainer:
    tenants, default_tenant = load_tenants(settings)
    handlers: Dict[str, QueryHandler] = {}
    for tenant_id, tenant in tenants.items():
        if not tenant.enabled:
            continue
        handlers[tenant_id] = build_handler(tenant, settings)
        LOGGER.info("Handler construido para tenant '%s'", tenant_id)

    if default_tenant not in handlers:
        # El default debe existir y estar habilitado; si no, usar el primero disponible.
        if handlers:
            default_tenant = next(iter(handlers))
            LOGGER.warning("Tenant por defecto deshabilitado; se usa '%s'", default_tenant)
        else:
            raise RuntimeError("No hay tenants habilitados para construir handlers")

    return AppContainer(
        settings=settings,
        handlers=handlers,
        default_tenant=default_tenant,
        tenants=tenants,
    )
