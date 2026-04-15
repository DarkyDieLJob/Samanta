"""Inicializa dependencias y contenedores de Samanta RAG."""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.prompts import ChatPromptTemplate

from .application.query_handler import QueryHandler
from .config import Settings, settings
from .domain.services import QueryService
from .infrastructure.llm.ollama_adapter import OllamaChatModel, OpenAIChatModel
from .infrastructure.vectorstore.faiss_adapter import FAISSVectorStoreAdapter


@dataclass(frozen=True)
class AppContainer:
    settings: Settings
    query_handler: QueryHandler


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
    query_handler = QueryHandler(query_service=query_service)
    return AppContainer(settings=settings, query_handler=query_handler)
