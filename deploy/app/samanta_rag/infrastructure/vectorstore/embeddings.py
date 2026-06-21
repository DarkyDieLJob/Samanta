"""Construcción de embeddings desacoplada del proveedor de chat."""

from __future__ import annotations


def build_embeddings(
    *,
    provider: str,
    model_name: str,
    ollama_base_url: str,
    openai_api_key: str = "",
):
    """Crea el adaptador de embeddings según el proveedor indicado.

    El proveedor de embeddings es independiente del proveedor de chat: se puede
    usar gpt-4o-mini para chat (OpenAI) y nomic-embed-text para embeddings (Ollama).
    """
    if provider == "openai" and openai_api_key:
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model=model_name, api_key=openai_api_key)
    from langchain_ollama import OllamaEmbeddings

    return OllamaEmbeddings(model=model_name, base_url=ollama_base_url)
