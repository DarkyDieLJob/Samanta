"""Caché de respuestas para reducir llamadas al LLM.

Combina dos mecanismos, ambos invalidados automáticamente cuando cambia el
corpus del tenant (se detecta vía hash del metadata del vectorstore):

- **FAQ precalculadas**: las ``example_questions`` del tenant se responden una
  sola vez por versión del corpus y luego se sirven desde caché.
- **Aprendizaje por similitud**: las preguntas que se repiten (idénticas o
  variantes semánticamente cercanas) se promueven a caché tras N ocurrencias.

El caché vive en disco, fuera del subdirectorio del vectorstore (que se borra en
cada reindexación), de modo que sobrevive a los reingest.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
import unicodedata
from pathlib import Path
from threading import Lock
from typing import Callable, Dict, List, Optional, Tuple

from ..constants import METADATA_FILENAME
from ..domain.entities import QueryResult

LOGGER = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[¿?¡!.,;:]+")


def normalize_question(question: str) -> str:
    """Normaliza una pregunta para comparación robusta.

    Pasa a minúsculas, elimina acentos, signos de puntuación frecuentes y
    colapsa espacios. No cambia el significado, solo la forma superficial.
    """
    text = question.strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


class AnswerCache:
    """Caché de respuestas por tenant, persistente y seguro entre hilos."""

    def __init__(
        self,
        *,
        tenant_id: str,
        cache_file: Path,
        vectorstore_path: Path,
        faq_questions: Tuple[str, ...] = (),
        faq_answers: Optional[Dict[str, str]] = None,
        embedder_factory: Optional[Callable[[], object]] = None,
        semantic_enabled: bool = True,
        sim_threshold: float = 0.92,
        promote_after: int = 3,
        max_entries: int = 200,
        max_observations: int = 500,
    ) -> None:
        self._tenant_id = tenant_id
        self._cache_file = cache_file
        self._vectorstore_path = vectorstore_path
        self._faq_norm = {normalize_question(q) for q in faq_questions}
        self._embedder_factory = embedder_factory
        self._semantic_enabled = semantic_enabled
        self._sim_threshold = sim_threshold
        self._promote_after = max(1, promote_after)
        self._max_entries = max_entries
        self._max_observations = max_observations

        # Respuestas predefinidas (FAQ): se sirven sin invocar al LLM ni
        # depender de la versión del corpus.  Son texto escrito a mano en
        # el config del tenant.
        self._predefined: Dict[str, str] = {}
        if faq_answers:
            for question, answer in faq_answers.items():
                self._predefined[normalize_question(question)] = answer

        self._lock = Lock()
        self._embedder = None  # carga perezosa
        self._embedder_failed = False
        self._version_cache: Optional[Tuple[str, str]] = None  # (signature, version)
        # Memo de embedding de la última pregunta para no recomputar entre
        # lookup() y record() dentro del mismo request.
        self._last_embed: Optional[Tuple[str, List[float]]] = None

        self._data = self._load()

    # --- Versión del corpus --------------------------------------------------

    @property
    def _metadata_file(self) -> Path:
        return self._vectorstore_path / METADATA_FILENAME

    def corpus_version(self) -> str:
        """Hash estable del contenido indexado del tenant.

        Cambia si cambia cualquier archivo del corpus (su hash o su cantidad de
        chunks). Si no hay metadata aún, devuelve ``"none"``.
        """
        meta = self._metadata_file
        if not meta.exists():
            return "none"
        try:
            raw = meta.read_text(encoding="utf-8")
        except OSError:
            return "none"
        # El signature se basa en el contenido real del archivo, no en stat,
        # para detectar cambios incluso si mtime y size coinciden.
        signature = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if self._version_cache and self._version_cache[0] == signature:
            return self._version_cache[1]
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return "none"
        parts = sorted(
            f"{item.get('source')}:{item.get('hash')}:{item.get('chunk_count')}"
            for item in data
        )
        digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
        self._version_cache = (signature, digest)
        return digest

    # --- Persistencia --------------------------------------------------------

    def _load(self) -> Dict[str, object]:
        if not self._cache_file.exists():
            return {"entries": [], "observations": []}
        try:
            raw = json.loads(self._cache_file.read_text(encoding="utf-8"))
            raw.setdefault("entries", [])
            raw.setdefault("observations", [])
            return raw
        except (json.JSONDecodeError, OSError):
            LOGGER.warning("[%s] Caché de respuestas corrupto; se reinicia", self._tenant_id)
            return {"entries": [], "observations": []}

    def _save(self) -> None:
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_file.with_suffix(self._cache_file.suffix + ".tmp")
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(tmp, self._cache_file)
        except OSError as exc:
            LOGGER.warning("[%s] No se pudo persistir el caché: %s", self._tenant_id, exc)

    # --- Embeddings (carga perezosa) ----------------------------------------

    def _embed(self, question: str) -> Optional[List[float]]:
        if not self._semantic_enabled or self._embedder_failed:
            return None
        q_norm = normalize_question(question)
        if self._last_embed and self._last_embed[0] == q_norm:
            return self._last_embed[1]
        if self._embedder is None and self._embedder_factory is not None:
            try:
                self._embedder = self._embedder_factory()
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("[%s] Embeddings no disponibles para caché: %s", self._tenant_id, exc)
                self._embedder_failed = True
                return None
        if self._embedder is None:
            return None
        try:
            vector = self._embedder.embed_query(question)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("[%s] Falló el embedding para caché: %s", self._tenant_id, exc)
            self._embedder_failed = True
            return None
        self._last_embed = (q_norm, vector)
        return vector

    # --- Búsqueda ------------------------------------------------------------

    def lookup(self, question: str) -> Optional[QueryResult]:
        """Devuelve una respuesta predefinida o cacheada, o None."""
        q_norm = normalize_question(question)

        # 0) Respuestas predefinidas (FAQ): siempre disponibles, sin LLM.
        if q_norm in self._predefined:
            LOGGER.info("[%s] FAQ predefined hit q=%r", self._tenant_id, question)
            return QueryResult(
                answer=self._predefined[q_norm],
                sources=[],
                cached=True,
            )

        with self._lock:
            version = self.corpus_version()
            entries = self._valid_entries(version)
            if not entries:
                return None

            # 1) Coincidencia exacta normalizada (sin costo de embedding).
            for entry in entries:
                if entry.get("q_norm") == q_norm:
                    return self._hit(entry)

            # 2) Coincidencia semántica (solo si está habilitada).
            if not self._semantic_enabled:
                return None
            vector = self._embed(question)
            if vector is None:
                return None
            best: Optional[dict] = None
            best_sim = 0.0
            for entry in entries:
                emb = entry.get("embedding")
                if not emb:
                    continue
                sim = _cosine(vector, emb)
                if sim > best_sim:
                    best_sim = sim
                    best = entry
            if best is not None and best_sim >= self._sim_threshold:
                return self._hit(best)
            return None

    def _valid_entries(self, version: str) -> List[dict]:
        return [
            e for e in self._data.get("entries", [])
            if e.get("version") == version and version != "none"
        ]

    def _hit(self, entry: dict) -> QueryResult:
        entry["hits"] = int(entry.get("hits", 0)) + 1
        entry["last_hit"] = time.time()
        self._save()
        LOGGER.info(
            "[%s] Cache HIT (%s) q=%r", self._tenant_id, entry.get("kind"), entry.get("question")
        )
        return QueryResult(
            answer=str(entry.get("answer", "")),
            sources=list(entry.get("sources", []) or []),
            cached=True,
        )

    # --- Registro tras una respuesta real del LLM ---------------------------

    def record(self, question: str, result: QueryResult) -> None:
        """Registra una respuesta recién generada por el LLM.

        - Si la pregunta tiene respuesta predefinida, no se registra (ya
          está servida sin LLM).
        - Si la pregunta es una FAQ del tenant sin respuesta predefinida,
          se cachea para futuras llamadas.
        - Si no, la cuenta como observación y la promueve tras N repeticiones
          (idénticas o variantes semánticamente cercanas).
        """
        if not result.answer.strip():
            return
        q_norm = normalize_question(question)
        if q_norm in self._predefined:
            return
        with self._lock:
            version = self.corpus_version()
            if version == "none":
                return
            if q_norm in self._faq_norm:
                self._upsert_entry("faq", question, q_norm, result, version)
                self._save()
                return
            self._observe_and_maybe_promote(question, q_norm, result, version)
            self._save()

    def _observe_and_maybe_promote(
        self, question: str, q_norm: str, result: QueryResult, version: str
    ) -> None:
        # Si ya existe una entrada (faq/learned) que cubre esta pregunta, no
        # hace falta volver a observarla.
        for entry in self._valid_entries(version):
            if entry.get("q_norm") == q_norm:
                return

        vector = self._embed(question)
        observations: List[dict] = self._data.setdefault("observations", [])  # type: ignore[assignment]

        match: Optional[dict] = None
        # Coincidencia exacta normalizada primero.
        for obs in observations:
            if obs.get("q_norm") == q_norm:
                match = obs
                break
        # Coincidencia semántica con observaciones existentes.
        if match is None and vector is not None and self._semantic_enabled:
            best_sim = 0.0
            best: Optional[dict] = None
            for obs in observations:
                emb = obs.get("embedding")
                if not emb:
                    continue
                sim = _cosine(vector, emb)
                if sim > best_sim:
                    best_sim = sim
                    best = obs
            if best is not None and best_sim >= self._sim_threshold:
                match = best

        if match is None:
            observations.append({
                "q_norm": q_norm,
                "question": question,
                "embedding": vector,
                "count": 1,
                "first_seen": time.time(),
            })
            self._trim_observations()
            return

        match["count"] = int(match.get("count", 0)) + 1
        match["last_seen"] = time.time()

        if match["count"] >= self._promote_after:
            # Promueve usando la pregunta canónica de la observación.
            canonical = str(match.get("question", question))
            canonical_norm = str(match.get("q_norm", q_norm))
            self._upsert_entry("learned", canonical, canonical_norm, result, version,
                               embedding=match.get("embedding"))
            observations.remove(match)
            LOGGER.info("[%s] Pregunta promovida a caché: %r", self._tenant_id, canonical)

    def _upsert_entry(
        self,
        kind: str,
        question: str,
        q_norm: str,
        result: QueryResult,
        version: str,
        embedding: Optional[List[float]] = None,
    ) -> None:
        entries: List[dict] = self._data.setdefault("entries", [])  # type: ignore[assignment]
        if embedding is None:
            embedding = self._embed(question)
        now = time.time()
        for entry in entries:
            if entry.get("q_norm") == q_norm:
                entry.update({
                    "kind": kind,
                    "question": question,
                    "answer": result.answer,
                    "sources": list(result.sources or []),
                    "embedding": embedding,
                    "version": version,
                    "updated": now,
                })
                return
        entries.append({
            "kind": kind,
            "question": question,
            "q_norm": q_norm,
            "answer": result.answer,
            "sources": list(result.sources or []),
            "embedding": embedding,
            "version": version,
            "hits": 0,
            "created": now,
            "updated": now,
        })
        self._trim_entries()

    # --- Mantenimiento -------------------------------------------------------

    def _trim_entries(self) -> None:
        entries: List[dict] = self._data.get("entries", [])  # type: ignore[assignment]
        if len(entries) <= self._max_entries:
            return
        # Conserva las FAQ y, entre learned, las más usadas/recientes.
        faqs = [e for e in entries if e.get("kind") == "faq"]
        learned = [e for e in entries if e.get("kind") != "faq"]
        learned.sort(key=lambda e: (int(e.get("hits", 0)), e.get("updated", 0)), reverse=True)
        keep = faqs + learned[: max(0, self._max_entries - len(faqs))]
        self._data["entries"] = keep

    def _trim_observations(self) -> None:
        observations: List[dict] = self._data.get("observations", [])  # type: ignore[assignment]
        if len(observations) <= self._max_observations:
            return
        observations.sort(key=lambda o: (int(o.get("count", 0)), o.get("first_seen", 0)), reverse=True)
        self._data["observations"] = observations[: self._max_observations]
