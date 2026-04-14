"""Configuración y utilidades para el agente RAG."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Tuple

from dotenv import load_dotenv

load_dotenv()


def _parse_allowed_ips(raw_value: str) -> Tuple[str, ...]:
    raw_value = (raw_value or "").strip()
    if not raw_value or raw_value == "*":
        return ()
    entries = [item.strip() for item in raw_value.split(",")]
    filtered = tuple(entry for entry in entries if entry)
    return filtered


def _parse_example_questions(raw_value: str) -> Tuple[str, ...]:
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return ()
    # Separa por '|' o salto de línea.
    separators = ["|", "\n"]
    parts: Iterable[str] = [raw_value]
    for separator in separators:
        if separator in raw_value:
            parts = raw_value.split(separator)
            break
    cleaned = tuple(question.strip() for question in parts if question.strip())
    return cleaned


@dataclass(frozen=True)
class Settings:
    env: Literal["production", "staging", "development"] = "production"
    ollama_base_url: str = "http://ollama:11434"
    model_name: str = "qwen3:8b"
    temperature: float = 0.3
    # Mensaje de sistema por defecto (puede ser sobrescrito por SYSTEM_PROMPT)
    system_prompt: str = (
        "Eres un asistente para clientes de un negocio local. "
        "Usa exclusivamente la información proporcionada en el contexto. "
        "Si no encuentras la respuesta en el contexto, responde que no sabes "
        "y sugiere contactar con un humano del negocio."
    )
    embedding_model_name: str = "nomic-embed-text"
    chunk_size: int = 500
    chunk_overlap: int = 50
    retrieval_k: int = 4
    documents_path: Path = Path("/data/markdown")
    vectorstore_path: Path = Path("/data/vectorstore/index")
    log_path: Path = Path("/logs")
    max_concurrent_sessions: int = 5
    allowed_ips: Tuple[str, ...] = ()
    example_questions: Tuple[str, ...] = ()


def get_settings() -> Settings:
    """Crea un objeto de configuración a partir de variables de entorno."""
    return Settings(
        env=os.getenv("ENV", Settings.env),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", Settings.ollama_base_url),
        model_name=os.getenv("MODEL_NAME", Settings.model_name),
        temperature=float(os.getenv("TEMPERATURE", Settings.temperature)),
        system_prompt=os.getenv("SYSTEM_PROMPT", Settings.system_prompt),
        embedding_model_name=os.getenv("EMBEDDING_MODEL_NAME", Settings.embedding_model_name),
        chunk_size=int(os.getenv("CHUNK_SIZE", Settings.chunk_size)),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", Settings.chunk_overlap)),
        retrieval_k=int(os.getenv("RETRIEVAL_K", Settings.retrieval_k)),
        documents_path=Path(os.getenv("DOCUMENTS_PATH", str(Settings.documents_path))).resolve(),
        vectorstore_path=Path(os.getenv("VECTORSTORE_PATH", str(Settings.vectorstore_path))).resolve(),
        log_path=Path(os.getenv("LOG_PATH", str(Settings.log_path))).resolve(),
        max_concurrent_sessions=int(
            os.getenv("MAX_CONCURRENT_SESSIONS", Settings.max_concurrent_sessions)
        ),
        allowed_ips=_parse_allowed_ips(os.getenv("ALLOWED_IPS", "*")),
        example_questions=_parse_example_questions(os.getenv("EXAMPLE_QUESTIONS", "")),
    )


settings = get_settings()
