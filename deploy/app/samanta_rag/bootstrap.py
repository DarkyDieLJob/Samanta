"""Inicializa dependencias y contenedores de Samanta RAG."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from langchain_core.prompts import ChatPromptTemplate

from .application.query_handler import QueryHandler
from .config import Settings, settings
from .domain.services import QueryService
from .infrastructure.llm.ollama_adapter import OllamaChatModel, OpenAIChatModel
from .infrastructure.vectorstore.faiss_adapter import FAISSVectorStoreAdapter
from .mcp.client import MCPClientError
from .mcp.registry import MCPRegistryError, load_registry_from_env
from .mcp.tool_registry import MCPToolRegistry, build_tool_registry
from .mcp.router import MCPRouter

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppContainer:
    settings: Settings
    query_handler: QueryHandler
    mcp_tool_registry: Optional[MCPToolRegistry] = None


def create_container() -> AppContainer:
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                settings.system_prompt,
            ),
            ("human", "Pregunta: {question}\n\nContexto:\n{context}"),
        ]
    )
    vectorstore_adapter = FAISSVectorStoreAdapter(
        settings.vectorstore_path,
        embedding_model_name=settings.embedding_model_name,
        base_url=settings.ollama_base_url,
    )
    if settings.llm_provider == "openai" and settings.openai_api_key:
        chat_model = OpenAIChatModel(
            model_name=settings.model_name,
            temperature=settings.temperature,
            prompt=prompt,
            api_key=settings.openai_api_key,
        )
    else:
        chat_model = OllamaChatModel(
            model_name=settings.model_name,
            temperature=settings.temperature,
            base_url=settings.ollama_base_url,
            prompt=prompt,
        )
    query_service = QueryService(vectorstore=vectorstore_adapter, chat_model=chat_model, top_k=settings.retrieval_k)
    query_handler = QueryHandler(query_service=query_service, fallback_top_k=settings.rag_faiss_topk)

    tool_registry: Optional[MCPToolRegistry] = None
    try:
        registry_config = load_registry_from_env()
    except MCPRegistryError as exc:
        LOGGER.warning("Registro MCP inválido: %s", exc)
    else:
        if registry_config:
            try:
                tool_registry = build_tool_registry(registry_config)
            except MCPClientError as exc:
                LOGGER.error("No se pudo descubrir herramientas MCP: %s", exc)
            else:
                mcp_router = MCPRouter(tool_registry, chat_model)
                query_handler.mcp_router = mcp_router

    return AppContainer(settings=settings, query_handler=query_handler, mcp_tool_registry=tool_registry)
