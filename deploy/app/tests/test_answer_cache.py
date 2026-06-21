"""Tests del caché de respuestas (FAQ precalculadas + aprendizaje)."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from samanta_rag.application.answer_cache import AnswerCache, normalize_question
from samanta_rag.constants import METADATA_FILENAME
from samanta_rag.domain.entities import QueryResult


def _write_metadata(vectorstore_path: Path, items: list[dict]) -> None:
    """Escribe un index_metadata.json simulando el resultado de un ingest."""
    vectorstore_path.mkdir(parents=True, exist_ok=True)
    (vectorstore_path / METADATA_FILENAME).write_text(
        json.dumps(items, ensure_ascii=False), encoding="utf-8"
    )


def _make_cache(
    tmp: Path,
    faq_questions: tuple[str, ...] = (),
    faq_answers: dict[str, str] | None = None,
    semantic_enabled: bool = False,
    promote_after: int = 3,
) -> AnswerCache:
    vs_path = tmp / "vectorstore"
    cache_file = tmp / "_answer_cache" / "test.json"
    return AnswerCache(
        tenant_id="test",
        cache_file=cache_file,
        vectorstore_path=vs_path,
        faq_questions=faq_questions,
        faq_answers=faq_answers,
        semantic_enabled=semantic_enabled,
        promote_after=promote_after,
    )


# --- normalize_question --------------------------------------------------

def test_normalize_strips_accents_and_punctuation():
    assert normalize_question("¿Qué haces?") == "que haces"
    assert normalize_question("  Hola,  mundo!!  ") == "hola mundo"
    assert normalize_question("¿Quién eres tú?") == "quien eres tu"


def test_normalize_case_insensitive():
    assert normalize_question("HOLA") == normalize_question("hola")


# --- FAQ caching ---------------------------------------------------------

def test_predefined_answer_served_without_llm():
    """Una FAQ con respuesta predefinida se sirve inmediatamente sin llamar al LLM."""
    with TemporaryDirectory() as tmp:
        cache = _make_cache(
            Path(tmp),
            faq_questions=("¿Quién es DieL?",),
            faq_answers={"¿Quién es DieL?": "Es un arquitecto de IA."},
        )
        # No hace falta metadata ni corpus: la respuesta es predefinida.
        cached = cache.lookup("¿Quién es DieL?")
        assert cached is not None
        assert cached.cached is True
        assert cached.answer == "Es un arquitecto de IA."


def test_predefined_answer_variant_normalized():
    """Variantes normalizadas de una FAQ predefinida también matchean."""
    with TemporaryDirectory() as tmp:
        cache = _make_cache(
            Path(tmp),
            faq_questions=("¿Quién es DieL?",),
            faq_answers={"¿Quién es DieL?": "Es un arquitecto de IA."},
        )
        cached = cache.lookup("quien es diel")
        assert cached is not None
        assert cached.answer == "Es un arquitecto de IA."


def test_predefined_answer_served_without_metadata():
    """Las respuestas predefinidas funcionan incluso sin index_metadata.json."""
    with TemporaryDirectory() as tmp:
        cache = _make_cache(
            Path(tmp),
            faq_questions=("¿Qué proyectos hizo?",),
            faq_answers={"¿Qué proyectos hizo?": "Samanta y más."},
        )
        # No se escribe metadata
        cached = cache.lookup("¿Qué proyectos hizo?")
        assert cached is not None
        assert cached.answer == "Samanta y más."


def test_predefined_not_overwritten_by_record():
    """record() no sobrescribe una respuesta predefinida."""
    with TemporaryDirectory() as tmp:
        cache = _make_cache(
            Path(tmp),
            faq_questions=("¿Quién es DieL?",),
            faq_answers={"¿Quién es DieL?": "Respuesta original."},
        )
        _write_metadata(cache._vectorstore_path, [{"source": "a.md", "hash": "x", "chunk_count": 1}])
        cache.record("¿Quién es DieL?", QueryResult(answer="Respuesta del LLM", sources=[]))
        cached = cache.lookup("¿Quién es DieL?")
        assert cached is not None
        assert cached.answer == "Respuesta original."


def test_faq_cached_after_first_record():
    """Una FAQ se cachea al primer record() y lookup() la devuelve."""
    with TemporaryDirectory() as tmp:
        cache = _make_cache(Path(tmp), faq_questions=("¿Qué haces?",))
        _write_metadata(cache._vectorstore_path, [{"source": "a.md", "hash": "x", "chunk_count": 1}])

        # Primera vez: no hay caché todavía
        assert cache.lookup("¿Qué haces?") is None

        # Simular respuesta del LLM
        result = QueryResult(answer="Soy un asistente", sources=["a.md"])
        cache.record("¿Qué haces?", result)

        # Segunda vez: debe servir desde caché
        cached = cache.lookup("¿Qué haces?")
        assert cached is not None
        assert cached.cached is True
        assert cached.answer == "Soy un asistente"
        assert cached.sources == ["a.md"]


def test_faq_variant_normalized_matches():
    """Variantes de una FAQ (con/sin signos, mayúsculas) deben matchear."""
    with TemporaryDirectory() as tmp:
        cache = _make_cache(Path(tmp), faq_questions=("¿Qué haces?",))
        _write_metadata(cache._vectorstore_path, [{"source": "a.md", "hash": "x", "chunk_count": 1}])

        cache.record("¿Qué haces?", QueryResult(answer="R", sources=[]))

        # Variante sin signos de interrogación
        cached = cache.lookup("que haces")
        assert cached is not None
        assert cached.answer == "R"


def test_non_fq_not_cached_on_first_record():
    """Una pregunta que no es FAQ no se cachea al primer record()."""
    with TemporaryDirectory() as tmp:
        cache = _make_cache(Path(tmp))
        _write_metadata(cache._vectorstore_path, [{"source": "a.md", "hash": "x", "chunk_count": 1}])

        cache.record("pregunta rara", QueryResult(answer="R", sources=[]))
        assert cache.lookup("pregunta rara") is None


# --- Cache invalidation by corpus version --------------------------------

def test_cache_invalidated_on_corpus_change():
    """Si cambia el metadata (nuevo hash), el caché se invalida."""
    with TemporaryDirectory() as tmp:
        cache = _make_cache(Path(tmp), faq_questions=("¿Qué haces?",))
        _write_metadata(cache._vectorstore_path, [{"source": "a.md", "hash": "v1", "chunk_count": 1}])

        cache.record("¿Qué haces?", QueryResult(answer="R1", sources=[]))
        assert cache.lookup("¿Qué haces?") is not None

        # Simular reingest: cambia el hash del documento
        _write_metadata(cache._vectorstore_path, [{"source": "a.md", "hash": "v2", "chunk_count": 1}])

        # El caché de la versión anterior ya no es válido
        assert cache.lookup("¿Qué haces?") is None


def test_cache_survives_when_no_metadata():
    """Sin metadata, no se cachea ni se sirve nada."""
    with TemporaryDirectory() as tmp:
        cache = _make_cache(Path(tmp), faq_questions=("¿Qué haces?",))
        # No se escribe metadata

        cache.record("¿Qué haces?", QueryResult(answer="R", sources=[]))
        assert cache.lookup("¿Qué haces?") is None


# --- Learned promotion ---------------------------------------------------

def test_learned_promotion_after_n_observations():
    """Una pregunta repetida N veces se promueve a caché."""
    with TemporaryDirectory() as tmp:
        cache = _make_cache(Path(tmp), promote_after=3)
        _write_metadata(cache._vectorstore_path, [{"source": "a.md", "hash": "x", "chunk_count": 1}])

        result = QueryResult(answer="R", sources=["a.md"])
        cache.record("pregunta repetida", result)
        assert cache.lookup("pregunta repetida") is None

        cache.record("pregunta repetida", result)
        assert cache.lookup("pregunta repetida") is None

        # Tercera observación: se promueve
        cache.record("pregunta repetida", result)
        cached = cache.lookup("pregunta repetida")
        assert cached is not None
        assert cached.cached is True
        assert cached.answer == "R"


def test_learned_promotion_with_exact_variants():
    """Variantes normalizadas de la misma pregunta cuentan como la misma observación."""
    with TemporaryDirectory() as tmp:
        cache = _make_cache(Path(tmp), promote_after=2)
        _write_metadata(cache._vectorstore_path, [{"source": "a.md", "hash": "x", "chunk_count": 1}])

        result = QueryResult(answer="R", sources=[])
        cache.record("¿Qué eres?", result)
        cache.record("que eres", result)  # variante normalizada

        # Debería estar promovida tras 2 observaciones (misma q_norm)
        cached = cache.lookup("¿Qué eres?")
        assert cached is not None
        assert cached.answer == "R"


# --- Persistence ---------------------------------------------------------

def test_cache_persists_to_disk():
    """El caché se persiste en JSON y sobrevive a una nueva instancia."""
    with TemporaryDirectory() as tmp:
        cache = _make_cache(Path(tmp), faq_questions=("¿Qué haces?",))
        _write_metadata(cache._vectorstore_path, [{"source": "a.md", "hash": "x", "chunk_count": 1}])

        cache.record("¿Qué haces?", QueryResult(answer="R", sources=[]))
        assert cache._cache_file.exists()

        # Nueva instancia leyendo el mismo archivo
        cache2 = AnswerCache(
            tenant_id="test",
            cache_file=cache._cache_file,
            vectorstore_path=cache._vectorstore_path,
            faq_questions=("¿Qué haces?",),
            semantic_enabled=False,
        )
        cached = cache2.lookup("¿Qué haces?")
        assert cached is not None
        assert cached.answer == "R"


# --- try_cached via QueryHandler -----------------------------------------

def test_try_cached_returns_none_without_cache():
    """QueryHandler.try_cached devuelve None si no hay answer_cache."""
    from samanta_rag.application.query_handler import QueryHandler
    from samanta_rag.domain.services import QueryService

    # QueryService no se usa en try_cached, pero QueryHandler es dataclass
    handler = QueryHandler(query_service=None)  # type: ignore[arg-type]
    assert handler.try_cached("hola") is None


# --- API only_cached mode ------------------------------------------------

def test_api_only_cached_returns_served_false_when_no_cache():
    """only_cached=True sin caché debe devolver served=False."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from samanta_rag.config import get_settings
    from samanta_rag.interface.api.dependencies import configure_dependencies
    from samanta_rag.interface.api import routes

    class FakeHandler:
        def try_cached(self, question: str):
            return None

    app = FastAPI()
    app.include_router(routes.router)
    configure_dependencies({"test": FakeHandler()}, "test", get_settings())
    client = TestClient(app)

    response = client.post("/api/query", json={"question": "hola", "only_cached": True})
    assert response.status_code == 200
    data = response.json()
    assert data["served"] is False
    assert data["cached"] is False
    assert data["answer"] == ""


def test_api_only_cached_returns_cached_when_available():
    """only_cached=True con caché debe devolver served=True y cached=True."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from samanta_rag.config import get_settings
    from samanta_rag.domain.entities import QueryResult
    from samanta_rag.interface.api.dependencies import configure_dependencies
    from samanta_rag.interface.api import routes

    class FakeHandler:
        def try_cached(self, question: str):
            return QueryResult(answer="cacheada", sources=["s.md"], cached=True)

    app = FastAPI()
    app.include_router(routes.router)
    configure_dependencies({"test": FakeHandler()}, "test", get_settings())
    client = TestClient(app)

    response = client.post("/api/query", json={"question": "hola", "only_cached": True})
    assert response.status_code == 200
    data = response.json()
    assert data["served"] is True
    assert data["cached"] is True
    assert data["answer"] == "cacheada"


def test_api_normal_query_includes_cached_flag():
    """Una query normal debe incluir el flag cached en la respuesta."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from samanta_rag.application.query_handler import QueryHandler
    from samanta_rag.config import get_settings
    from samanta_rag.domain.entities import QueryResult, VectorStoreSummary
    from samanta_rag.interface.api.dependencies import configure_dependencies
    from samanta_rag.interface.api import routes

    class FakeQueryHandler(QueryHandler):
        def __init__(self):
            self._tenant = "test"

        def run(self, question: str) -> QueryResult:
            return QueryResult(answer="R", sources=["s.md"], cached=True)

        def summary(self):
            return VectorStoreSummary(total_files=1, total_chunks=1, last_updated=None)

        def is_available(self) -> bool:
            return True

        def refresh_vectorstore(self) -> None:
            pass

        def mcp_registry_summary(self):
            return {"enabled": False}

        def mcp_metrics_snapshot(self):
            return []

    app = FastAPI()
    app.include_router(routes.router)
    configure_dependencies({"test": FakeQueryHandler()}, "test", get_settings())
    client = TestClient(app)

    response = client.post("/api/query", json={"question": "hola"})
    assert response.status_code == 200
    data = response.json()
    assert data["cached"] is True
    assert data["served"] is True
