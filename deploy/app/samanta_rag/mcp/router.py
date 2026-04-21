"""Heurísticas de ruteo por intención para herramientas MCP."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List, Optional, Sequence, TypeVar

from ..domain.entities import ChatModelPort, QueryResult
from .client import MCPClient, MCPClientError
from .observability import MCPMetricsRecorder
from .tool_registry import MCPToolRegistry, RegisteredTool

LOGGER = logging.getLogger(__name__)
_MAX_CONTEXT_CHARS = 4000
_T = TypeVar("_T")


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
            if score > 0.0:
                candidates.append(_ToolCandidate(tool=tool, score=score))
        return candidates

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
            return {
                "q": question,
                "limit": 10,
            }
        if name == "health.ping":
            return {}
        return {
            "q": question,
        }

    def _build_result(self, question: str, tool: RegisteredTool, payload: object) -> QueryResult:
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
            events = payload.get("events")
            if isinstance(events, list) and events:
                lines = ["Eventos en vivo:"]
                for item in events[:5]:
                    if not isinstance(item, dict):
                        continue
                    title = str(item.get("title") or item.get("name") or item.get("label") or "Evento")
                    date = item.get("date") or item.get("datetime") or item.get("starts_at")
                    venue = item.get("venue") or item.get("place") or item.get("location")
                    line = f"- {title}"
                    if date:
                        line += f" · {date}"
                    if venue:
                        line += f" · {venue}"
                    lines.append(line)
                if len(lines) > 1:
                    return "\n".join(lines)
        raw = json.dumps(payload, ensure_ascii=False, indent=2) if isinstance(payload, (dict, list)) else str(payload)
        return raw[:_MAX_CONTEXT_CHARS]

