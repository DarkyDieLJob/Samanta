"""Configuración y utilidades para el agente RAG."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Literal, Optional, Tuple

from dotenv import load_dotenv

LOGGER = logging.getLogger(__name__)

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
    llm_provider: Literal["ollama", "openai"] = "ollama"
    model_name: str = "qwen3:8b"
    temperature: float = 0.3
    # Mensaje de sistema por defecto (puede ser sobrescrito por SYSTEM_PROMPT)
    system_prompt: str = (
        "Eres un asistente para clientes de un negocio local. "
        "Usa exclusivamente la información proporcionada en el contexto. "
        "Si no encuentras la respuesta en el contexto, responde que no sabes "
        "y sugiere contactar con un humano del negocio."
    )
    embedding_provider: Literal["ollama", "openai"] = "ollama"
    embedding_model_name: str = "nomic-embed-text"
    chunk_size: int = 500
    chunk_overlap: int = 50
    retrieval_k: int = 4
    documents_path: Path = Path("/data/markdown")
    vectorstore_path: Path = Path("/data/vectorstore")
    log_path: Path = Path("/logs")
    max_concurrent_sessions: int = 5
    allowed_ips: Tuple[str, ...] = ()
    example_questions: Tuple[str, ...] = ()
    # OpenAI
    openai_api_key: str = ""
    # Zona horaria de la app y top-k para degradación FAISS (opcional)
    app_timezone: str = "UTC"
    rag_faiss_topk: int = 0
    # Caché de respuestas (FAQ precalculadas + aprendizaje por similitud)
    answer_cache_enabled: bool = True
    answer_cache_sim_threshold: float = 0.92
    answer_cache_promote_after: int = 3
    answer_cache_max_entries: int = 200
    answer_cache_max_observations: int = 500


def get_settings() -> Settings:
    """Crea un objeto de configuración a partir de variables de entorno."""
    return Settings(
        env=os.getenv("ENV", Settings.env),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", Settings.ollama_base_url),
        llm_provider=os.getenv("LLM_PROVIDER", Settings.llm_provider),
        model_name=os.getenv("MODEL_NAME", Settings.model_name),
        temperature=float(os.getenv("TEMPERATURE", Settings.temperature)),
        system_prompt=os.getenv("SYSTEM_PROMPT", Settings.system_prompt),
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", Settings.embedding_provider),
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
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        app_timezone=os.getenv("APP_TIMEZONE", Settings.app_timezone),
        rag_faiss_topk=int(os.getenv("RAG_FAISS_TOPK", Settings.rag_faiss_topk)),
        answer_cache_enabled=os.getenv(
            "ANSWER_CACHE_ENABLED", str(Settings.answer_cache_enabled)
        ).strip().lower() in ("1", "true", "yes", "on"),
        answer_cache_sim_threshold=float(
            os.getenv("ANSWER_CACHE_SIM_THRESHOLD", Settings.answer_cache_sim_threshold)
        ),
        answer_cache_promote_after=int(
            os.getenv("ANSWER_CACHE_PROMOTE_AFTER", Settings.answer_cache_promote_after)
        ),
        answer_cache_max_entries=int(
            os.getenv("ANSWER_CACHE_MAX_ENTRIES", Settings.answer_cache_max_entries)
        ),
        answer_cache_max_observations=int(
            os.getenv("ANSWER_CACHE_MAX_OBSERVATIONS", Settings.answer_cache_max_observations)
        ),
    )


settings = get_settings()


@dataclass(frozen=True)
class TenantConfig:
    """Configuración inmutable de un tenant (proyecto) servido por Samanta."""

    id: str
    system_prompt: str
    documents_path: Path
    vectorstore_path: Path
    llm_provider: str = "ollama"  # "ollama" | "openai"
    model_name: str = "qwen3:8b"
    embedding_provider: str = "ollama"  # "ollama" | "openai"
    embedding_model_name: str = "nomic-embed-text"
    temperature: float = 0.3
    retrieval_k: int = 4
    example_questions: Tuple[str, ...] = ()
    faq_answers: Dict[str, str] = ()  # type: ignore[assignment]
    mcp_registry_path: Optional[Path] = None  # None = MCP por path desactivado
    mcp_from_env: bool = False  # True solo para el tenant 'default' (retrocompat MCP por env)
    enabled: bool = True


def _resolve_tenant_path(raw: str, base: Path, json_dir: Path) -> Path:
    """Resuelve un path de tenant.

    Si ``raw`` es absoluto se devuelve tal cual. Si es relativo, se resuelve
    desde el directorio del JSON de tenant, permitiendo que los mismos archivos
    funcionen dentro de Docker y en desarrollo local.
    """
    path = Path(raw)
    if path.is_absolute():
        return path
    return (json_dir / path).resolve()


def _tenant_from_dict(data: dict, base_settings: Settings, json_path: Path) -> TenantConfig:
    """Construye un TenantConfig a partir del JSON de un tenant.

    Los campos ausentes caen a los defaults del Settings global (retrocompat).
    Los paths relativos se resuelven desde el directorio del JSON.
    """
    tenant_id = str(data["id"]).strip()
    if not tenant_id:
        raise ValueError("El tenant debe tener un 'id' no vacío")

    json_dir = json_path.parent

    mcp_path_raw = data.get("mcp_registry_path")
    mcp_registry_path = (
        _resolve_tenant_path(mcp_path_raw, base_settings.documents_path, json_dir)
        if mcp_path_raw
        else None
    )

    return TenantConfig(
        id=tenant_id,
        system_prompt=str(data.get("system_prompt", base_settings.system_prompt)),
        documents_path=_resolve_tenant_path(
            data.get("documents_path", str(base_settings.documents_path)),
            base_settings.documents_path,
            json_dir,
        ),
        vectorstore_path=_resolve_tenant_path(
            data.get("vectorstore_path", str(base_settings.vectorstore_path)),
            base_settings.vectorstore_path,
            json_dir,
        ),
        llm_provider=str(data.get("llm_provider", base_settings.llm_provider)),
        model_name=str(data.get("model_name", base_settings.model_name)),
        embedding_provider=str(data.get("embedding_provider", base_settings.embedding_provider)),
        embedding_model_name=str(data.get("embedding_model_name", base_settings.embedding_model_name)),
        temperature=float(data.get("temperature", base_settings.temperature)),
        retrieval_k=int(data.get("retrieval_k", base_settings.retrieval_k)),
        example_questions=tuple(data.get("example_questions", []) or ()),
        faq_answers=dict(data.get("faq_answers", {}) or {}),
        mcp_registry_path=mcp_registry_path,
        mcp_from_env=False,
        enabled=bool(data.get("enabled", True)),
    )


def _default_tenant_from_settings(base_settings: Settings) -> TenantConfig:
    """Tenant 'default' derivado del Settings global (retrocompatibilidad total)."""
    return TenantConfig(
        id="default",
        system_prompt=base_settings.system_prompt,
        documents_path=base_settings.documents_path,
        vectorstore_path=base_settings.vectorstore_path,
        llm_provider=base_settings.llm_provider,
        model_name=base_settings.model_name,
        embedding_provider=base_settings.embedding_provider,
        embedding_model_name=base_settings.embedding_model_name,
        temperature=base_settings.temperature,
        retrieval_k=base_settings.retrieval_k,
        example_questions=base_settings.example_questions,
        mcp_registry_path=None,
        mcp_from_env=True,  # el tenant default conserva el MCP por variables de entorno
        enabled=True,
    )


def load_tenants(base_settings: Settings = settings) -> Tuple[Dict[str, TenantConfig], str]:
    """Carga los tenants desde TENANTS_PATH (un *.json por tenant).

    Si no hay directorio o no hay JSON válidos, devuelve un único tenant 'default'
    construido desde el Settings global (retrocompatibilidad).

    Returns:
        (tenants, default_tenant_id)
    """
    tenants_path = Path(os.getenv("TENANTS_PATH", "/data/tenants"))
    tenants: Dict[str, TenantConfig] = {}

    if tenants_path.exists() and tenants_path.is_dir():
        for json_file in sorted(tenants_path.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                tenant = _tenant_from_dict(data, base_settings, json_file)
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
                LOGGER.warning("Tenant inválido en %s: %s", json_file, exc)
                continue
            if tenant.id in tenants:
                LOGGER.warning("Tenant duplicado '%s' en %s, se ignora", tenant.id, json_file)
                continue
            tenants[tenant.id] = tenant

    if not tenants:
        default_tenant = _default_tenant_from_settings(base_settings)
        return {default_tenant.id: default_tenant}, default_tenant.id

    requested_default = os.getenv("DEFAULT_TENANT", "").strip()
    if requested_default and requested_default in tenants:
        default_tenant_id = requested_default
    else:
        if requested_default:
            LOGGER.warning(
                "DEFAULT_TENANT='%s' no existe entre los tenants; se usa el primero", requested_default
            )
        default_tenant_id = next(iter(tenants))

    return tenants, default_tenant_id
