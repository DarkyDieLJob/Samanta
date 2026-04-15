"""Adaptador de modelo conversacional basado en Ollama."""

from __future__ import annotations

from typing import List

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from ...domain.entities import ChatModelPort


class OllamaChatModel(ChatModelPort):
    """Implementación del puerto de chat usando Ollama."""

    def __init__(
        self,
        *,
        model_name: str,
        temperature: float,
        base_url: str,
        prompt: ChatPromptTemplate,
    ) -> None:
        self._model_name = model_name
        self._temperature = temperature
        self._base_url = base_url
        self._prompt = prompt

    def generate(self, question: str, context: str) -> str:  # type: ignore[override]
        llm = ChatOllama(
            model=self._model_name,
            base_url=self._base_url,
            temperature=self._temperature,
        )
        messages = self._prompt.format_messages(question=question, context=context)
        response = llm.invoke(messages)
        content = response.content if hasattr(response, "content") else str(response)
        return content


class OpenAIChatModel(ChatModelPort):
    """Implementación del puerto de chat usando OpenAI API (langchain-openai)."""

    def __init__(
        self,
        *,
        model_name: str,
        temperature: float,
        prompt: ChatPromptTemplate,
        api_key: str,
    ) -> None:
        self._model_name = model_name
        self._temperature = temperature
        self._prompt = prompt
        self._api_key = api_key

    def generate(self, question: str, context: str) -> str:  # type: ignore[override]
        llm = ChatOpenAI(
            model=self._model_name,
            temperature=self._temperature,
            api_key=self._api_key,
        )
        messages = self._prompt.format_messages(question=question, context=context)
        response = llm.invoke(messages)
        content = response.content if hasattr(response, "content") else str(response)
        return content
