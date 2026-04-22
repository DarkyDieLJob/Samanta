"""Heurísticas de ruteo por intención para herramientas MCP."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Set, TypeVar

from ..domain.entities import ChatModelPort, QueryResult
from .client import MCPClient, MCPClientError
from .observability import MCPMetricsRecorder
from .tool_registry import MCPToolRegistry, RegisteredTool

LOGGER = logging.getLogger(__name__)
_MAX_CONTEXT_CHARS = 4000
_T = TypeVar("_T")

_INTENT_BONUSES: Dict[str, List[str]] = {
    "events.past": ["pasad", "ayer", "anterior", "histori"],
    "events.future": ["próxim", "proxim", "futur", "vendrá", "vendran"],
    "events.this_week": ["esta semana", "esta sem"],
}

_DETAIL_KEYWORDS: List[str] = [
    "de que se trata",
    "de que trata",
    "que es",
    "que significa",
    "descripcion",
    "describ",
    "detalle",
    "detalles",
    "informacion",
    "info",
    "contame",
    "cuentame",
]

_LIST_INTENT_HINTS: Sequence[str] = (
    "evento",
    "eventos",
    "listar",
    "listame",
    "listarme",
    "lista",
    "mostrar",
    "pasado",
    "pasados",
    "proximo",
    "proximos",
    "semana",
)


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    without_diacritics = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return without_diacritics.lower()


def _tokenize(value: str) -> Set[str]:
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in _normalize_text(value))
    return {token for token in cleaned.split() if len(token) > 2}


def _parse_datetime(value: object) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_datetime_human(value: object) -> Optional[str]:
    dt = _parse_datetime(value)
    if dt is None:
        return None
    return dt.strftime("%d/%m/%Y %H:%M")


def _event_location(event: Dict[str, object]) -> Optional[str]:
    zone = event.get("zone") or event.get("venue") or event.get("place") or event.get("location")
    room = event.get("room") or event.get("area")
    if zone and room:
        return f"{zone}/{room}"
    if zone:
        return str(zone)
    if room:
        return str(room)
    return None


def _format_price_range(event: Dict[str, object]) -> Optional[str]:
    price_range = event.get("price_range")
    if isinstance(price_range, dict):
        parts: List[str] = []
        for label, amount in price_range.items():
            if not amount:
                continue
            label_norm = _normalize_text(str(label))
            if "anticip" in label_norm or "pre" in label_norm:
                parts.append(f"Ant: {amount}")
            elif "puerta" in label_norm or "door" in label_norm:
                parts.append(f"Puerta: {amount}")
            else:
                parts.append(f"{str(label).capitalize()}: {amount}")
        if parts:
            return " / ".join(dict.fromkeys(parts))
    price = event.get("price")
    if price:
        return str(price)
    return None


def _clean_description_text(text: str) -> str:
    normalized = (
        text.replace("✅", ". ")
        .replace("♦️", ". ")
        .replace("•", "- ")
        .replace("🕒", "Horarios: ")
    )
    for marker in (
        "Entrada:",
        "Entradas:",
        "Horarios:",
        "Reservas y consultas",
        "Reservas:",
        "Promos",
        "Pagos",
        "Alias:",
    ):
        normalized = re.sub(rf"\s+({re.escape(marker)})", r". \1", normalized)
    original_lines = normalized.splitlines()
    cleaned_lines: List[str] = []
    for line in original_lines:
        stripped = line.strip()
        if not stripped:
            continue
        stripped = re.sub(r"^[•\-–\*\u2022\u25CF\u25AA\u25B6\u279C\u27A4\u27B2\u2666\u25C6\u25BA\s]+", "", stripped)
        stripped = re.sub(r"^([#@•\-–\*]+\s*)", "", stripped)
        stripped = stripped.lstrip(".,;:-–—· ")
        cleaned_lines.append(stripped)
    compact = " ".join(cleaned_lines)
    compact = re.sub(r"\s+", " ", compact)
    return compact.strip()


def _summarize_description(text: str, *, max_sentences: int = 2, max_chars: int = 320) -> Optional[str]:
    cleaned = _clean_description_text(text)
    if not cleaned:
        return None
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    fallback = cleaned[:max_chars].rstrip()
    summary_parts: List[str] = []
    for sentence in sentences:
        candidate = sentence.strip()
        if not candidate:
            continue
        summary_parts.append(candidate)
        summary_text = " ".join(summary_parts)
        if len(summary_parts) >= max_sentences or len(summary_text) >= max_chars:
            return summary_text[:max_chars].rstrip()
    summary = " ".join(summary_parts).strip()
    return summary[:max_chars].rstrip() if summary else fallback


def _join_clause(prefix: str, parts: Iterable[str]) -> Optional[str]:
    items = [part for part in parts if part]
    if not items:
        return None
    if len(items) == 1:
        return f"{prefix}{items[0]}."
    if len(items) == 2:
        return f"{prefix}{items[0]} y {items[1]}."
    return f"{prefix}{', '.join(items[:-1])} y {items[-1]}."


def _extract_event_items(payload: object) -> List[Dict[str, object]]:
    items: List[Dict[str, object]] = []

    def _visit(obj: object) -> None:
        if isinstance(obj, dict):
            direct_events = obj.get("events")
            if isinstance(direct_events, list):
                for event in direct_events:
                    if isinstance(event, dict):
                        items.append(event)

            list_items = obj.get("items")
            if isinstance(list_items, list):
                for event in list_items:
                    if isinstance(event, dict):
                        items.append(event)

            nested_result = obj.get("result")
            if isinstance(nested_result, (dict, list)):
                _visit(nested_result)

            content = obj.get("content")
            if isinstance(content, list):
                for entry in content:
                    if isinstance(entry, dict):
                        text = entry.get("text")
                        if isinstance(text, str):
                            stripped = text.strip()
                            if stripped.startswith("{") or stripped.startswith("["):
                                try:
                                    parsed = json.loads(stripped)
                                except json.JSONDecodeError:
                                    continue
                                _visit(parsed)
                        else:
                            _visit(entry)
        elif isinstance(obj, list):
            for element in obj:
                _visit(element)

    _visit(payload)
    return items


def _format_event_line(event: Dict[str, object]) -> str:
    title = str(event.get("title") or event.get("name") or event.get("label") or "Evento")
    raw_date = (
        event.get("date_start")
        or event.get("date")
        or event.get("datetime")
        or event.get("starts_at")
        or event.get("startsAt")
    )
    human_date = _format_datetime_human(raw_date)
    location = _event_location(event)
    line = f"- {title}"
    detail_bits: List[str] = []
    if human_date:
        detail_bits.append(human_date)
    elif raw_date:
        detail_bits.append(str(raw_date))
    if location:
        detail_bits.append(location)
    price_info = _format_price_range(event)
    if price_info:
        detail_bits.append(f"entradas {price_info}")
    availability = event.get("availability")
    if isinstance(availability, str) and availability and availability.lower() not in {"unknown", "desconocido"}:
        detail_bits.append(availability)
    if detail_bits:
        line = f"{line} — {' · '.join(detail_bits)}"
    return line


def _wants_event_detail(question: str) -> bool:
    normalized_question = _normalize_text(question)
    return any(keyword in normalized_question for keyword in _DETAIL_KEYWORDS)


def _match_event_for_question(question: str, events: List[Dict[str, object]]) -> Optional[Dict[str, object]]:
    question_tokens = _tokenize(question)
    normalized_question = _normalize_text(question)
    best_event: Optional[Dict[str, object]] = None
    best_score = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        title = str(event.get("title") or event.get("name") or event.get("label") or "").strip()
        normalized_title = _normalize_text(title) if title else ""
        event_tokens = _tokenize(title)
        artists = event.get("artists")
        if isinstance(artists, list):
            for artist in artists:
                if isinstance(artist, str):
                    event_tokens.update(_tokenize(artist))
        for key in ("slug", "id", "uuid", "code"):
            value = event.get(key)
            if isinstance(value, str):
                event_tokens.update(_tokenize(value))
            elif isinstance(value, int):
                event_tokens.add(str(value))
        shared = question_tokens & event_tokens
        score = len(shared)
        if normalized_title and normalized_title in normalized_question:
            score += max(1, len(event_tokens))
        if score > best_score:
            best_score = score
            best_event = event
    if best_score > 0 and best_event:
        return best_event
    return None


def _format_event_detail(event: Dict[str, object]) -> str:
    title = str(event.get("title") or event.get("name") or event.get("label") or "Evento")
    raw_date = (
        event.get("date_start")
        or event.get("date")
        or event.get("datetime")
        or event.get("starts_at")
        or event.get("startsAt")
    )
    human_date = _format_datetime_human(raw_date)
    location = _event_location(event)
    intro_parts: List[str] = []
    if human_date:
        intro_parts.append(f"el {human_date}")
    elif raw_date:
        intro_parts.append(f"el {raw_date}")
    if location:
        intro_parts.append(f"en {location}")
    price_info = _format_price_range(event)
    if price_info:
        intro_parts.append(f"con entradas {price_info}")
    availability = event.get("availability")
    if isinstance(availability, str) and availability and availability.lower() not in {"unknown", "desconocido"}:
        intro_parts.append(f"hay {availability}")
    lines = [title]
    intro_sentence = _join_clause("Se presenta ", intro_parts)
    if intro_sentence:
        lines.append(intro_sentence)
    else:
        lines.append("Todavía no hay datos confirmados de fecha o lugar.")
    artists = event.get("artists")
    if isinstance(artists, list):
        artists_clean = [str(artist) for artist in artists if isinstance(artist, (str, int))]
        if artists_clean:
            artist_sentence = _join_clause("Participan ", artists_clean)
            if artist_sentence:
                lines.append(artist_sentence)
    url = event.get("url")
    if isinstance(url, str) and url:
        lines.append(f"Más info: {url}")
    description = event.get("description_public") or event.get("description_raw")
    summary: Optional[str] = None
    if isinstance(description, str):
        summary = _summarize_description(description)
    lines.append("")
    if summary:
        lines.append(f"Resumen: {summary}")
    else:
        lines.append("No hay descripción publicada para este evento.")
    return "\n".join(lines)


def _format_event_list(events: List[Dict[str, object]]) -> str:
    lines = ["Estos son los últimos 5 eventos publicados:"]
    for event in events[:5]:
        if isinstance(event, dict):
            lines.append(_format_event_line(event))
    return "\n".join(lines)


def _format_events_answer(question: str, events: List[Dict[str, object]]) -> str:
    normalized_question = _normalize_text(question)
    matched_event = _match_event_for_question(question, events)
    if matched_event:
        if _wants_event_detail(question) or len(events) == 1:
            return _format_event_detail(matched_event)
        if not any(hint in normalized_question for hint in _LIST_INTENT_HINTS):
            return _format_event_detail(matched_event)
    return _format_event_list(events)


def _run_blocking(factory: Callable[[], Awaitable[_T]]) -> _T:
    """Ejecuta una corrutina incluso si ya hay un loop activo (usa hilo separado)."""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result: Dict[str, _T] = {}
    error: Dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(factory())
        except BaseException as exc:  # noqa: BLE001 - re-lanzar luego
            error["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if error:
        raise error["error"]
    if "value" not in result:
        raise MCPClientError("Respuesta vacía del proveedor MCP")
    return result["value"]


@dataclass(frozen=True)
class MCPRouterAttempt:
    status: str  # success | no_registry | no_match | error
    result: Optional[QueryResult] = None
    message: Optional[str] = None


@dataclass(frozen=True)
class _ToolCandidate:
    tool: RegisteredTool
    score: float


class MCPRouter:
    """Selecciona herramientas MCP por intención y orquesta fallback."""

    def __init__(self, registry: MCPToolRegistry, chat_model: ChatModelPort, *, metrics: Optional[MCPMetricsRecorder] = None) -> None:
        self._registry = registry
        self._chat_model = chat_model
        self._metrics = metrics or MCPMetricsRecorder()

    def try_answer(self, question: str) -> MCPRouterAttempt:
        tools = self._registry.all_tools()
        if not tools:
            return MCPRouterAttempt(status="no_registry")
        candidates = self._score_candidates(question, tools)
        if not candidates:
            return MCPRouterAttempt(status="no_match")
        selected_group = self._select_group(candidates)
        if not selected_group:
            return MCPRouterAttempt(status="no_match")

        errors: List[str] = []
        for tool in selected_group:
            client = MCPClient(tool.provider)
            try:
                start = time.perf_counter()
                payload = _run_blocking(
                    lambda: client.call_tool(tool.tool_name, self._build_arguments(question, tool))
                )
            except MCPClientError as exc:
                LOGGER.warning("Fallo tool %s.%s: %s", tool.provider.name, tool.tool_name, exc)
                self._metrics.record_failure(tool.provider.name, tool.tool_name, status="error", error_message=str(exc))
                errors.append(str(exc))
                continue
            try:
                result = self._build_result(question, tool, payload)
            except Exception as exc:  # noqa: BLE001 - preferimos degradar con mensaje
                LOGGER.warning("No se pudo formatear respuesta MCP %s.%s: %s", tool.provider.name, tool.tool_name, exc)
                self._metrics.record_failure(tool.provider.name, tool.tool_name, status="error", error_message=str(exc))
                errors.append(str(exc))
                continue
            latency_ms = max(0.0, (time.perf_counter() - start) * 1000)
            retries = payload.get("retries", 0) if isinstance(payload, dict) else 0
            self._metrics.record_success(tool.provider.name, tool.tool_name, latency_ms=latency_ms, retries=retries)
            return MCPRouterAttempt(status="success", result=result)

        label = selected_group[0].tool_name if selected_group else "tool"
        message = (
            f"No se pudo acceder a datos en vivo ({label}: {selected_group[0].provider.name})"
            if selected_group
            else "No se pudo acceder a datos en vivo"
        )
        if errors:
            message = f"{message}. Último error: {errors[-1]}"
        return MCPRouterAttempt(status="error", message=message)

    def _score_candidates(self, question: str, tools: Sequence[RegisteredTool]) -> List[_ToolCandidate]:
        q = question.lower()
        candidates: List[_ToolCandidate] = []
        for tool in tools:
            score = 0.0
            if tool.provider.required:
                score += 5.0
            if tool.provider.preferred:
                score += 0.5
            for domain in tool.domains:
                domain = domain.lower()
                if domain and domain in q:
                    score += 2.5
            for keyword in tool.keywords:
                keyword = keyword.lower()
                if keyword and keyword in q:
                    score += 1.0
            if tool.tool_name.lower() in q:
                score += 0.75
            if tool.provider.name.lower() in q:
                score += 0.5
            bonuses = _INTENT_BONUSES.get(tool.tool_name.lower())
            if bonuses:
                for token in bonuses:
                    if token in q:
                        score += 3.0
            if score > 0.0:
                candidates.append(_ToolCandidate(tool=tool, score=score))
        return candidates

    def registry_summary(self) -> Dict[str, object]:
        return self._registry.summary()

    def metrics_snapshot(self) -> List[Dict[str, object]]:
        return self._metrics.snapshot()

    def _select_group(self, candidates: Sequence[_ToolCandidate]) -> List[RegisteredTool]:
        if not candidates:
            return []
        best = max(candidates, key=lambda c: c.score)
        if best.score <= 0.0 and not best.tool.provider.required:
            return []
        name = best.tool.tool_name
        group = [c for c in candidates if c.tool.tool_name == name]
        group.sort(
            key=lambda c: (
                bool(c.tool.provider.required),
                bool(c.tool.provider.preferred),
                c.score,
            ),
            reverse=True,
        )
        return [c.tool for c in group]

    def _build_arguments(self, question: str, tool: RegisteredTool) -> Dict[str, object]:
        name = tool.tool_name.lower()
        if name.startswith("events."):
            base_args: Dict[str, object] = {
                "limit": 10,
            }
            if name == "events.this_week":
                base_args["q"] = ""
            now = datetime.now(timezone.utc).astimezone()
            if name == "events.past":
                since = (now - timedelta(days=45)).replace(microsecond=0)
                base_args["since"] = since.isoformat()
            elif name == "events.future":
                until = (now + timedelta(days=60)).replace(microsecond=0)
                base_args["until"] = until.isoformat()
            return base_args
        if name == "health.ping":
            return {}
        return {
            "q": question,
        }

    def _build_result(self, question: str, tool: RegisteredTool, payload: object) -> QueryResult:
        events = _extract_event_items(payload)
        if events:
            answer = _format_events_answer(question, events)
        else:
            context = self._format_context(tool, payload)
            answer = self._chat_model.generate(question, context)
        source_label = self._source_label(tool)
        annotated_answer = f"{answer}\n\n{source_label}"
        return QueryResult(answer=annotated_answer, sources=[source_label])

    def _source_label(self, tool: RegisteredTool) -> str:
        domain = tool.domains[0] if tool.domains else tool.tool_name
        return f"({domain}: {tool.provider.name})"

    def _format_context(self, tool: RegisteredTool, payload: object) -> str:
        if isinstance(payload, dict):
            events = _extract_event_items(payload)
            if events:
                lines = ["Eventos en vivo (MCP):"]
                for item in events[:5]:
                    title = str(item.get("title") or item.get("name") or item.get("label") or "Evento")
                    date = (
                        item.get("date_start")
                        or item.get("date")
                        or item.get("datetime")
                        or item.get("starts_at")
                        or item.get("startsAt")
                    )
                    zone = item.get("zone") or item.get("venue") or item.get("place") or item.get("location")
                    room = item.get("room") or item.get("area")
                    line_parts = [f"- {title}"]
                    if date:
                        line_parts.append(str(date))
                    if zone and room:
                        line_parts.append(f"{zone}/{room}")
                    elif zone:
                        line_parts.append(str(zone))
                    elif room:
                        line_parts.append(str(room))
                    price = item.get("price_range")
                    if isinstance(price, dict):
                        anticipada = price.get("anticipada") or price.get("pre_sale")
                        puerta = price.get("puerta") or price.get("door")
                        if anticipada or puerta:
                            price_bits = []
                            if anticipada:
                                price_bits.append(f"Ant: {anticipada}")
                            if puerta:
                                price_bits.append(f"Puerta: {puerta}")
                            line_parts.append(" / ".join(price_bits))
                    lines.append(" · ".join(line_parts))
                if len(lines) > 1:
                    return "\n".join(lines)
        raw = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
        return raw[:_MAX_CONTEXT_CHARS]

