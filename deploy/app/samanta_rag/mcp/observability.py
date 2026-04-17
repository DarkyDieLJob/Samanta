"""Registro en memoria de métricas MCP (latencias, errores, percentiles)."""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Deque, Dict, List, Optional


@dataclass
class _MetricWindow:
    latencies_ms: Deque[float] = field(default_factory=deque)
    successes: int = 0
    errors: int = 0
    timeouts: int = 0
    retries: int = 0
    last_error: Optional[str] = None


class MCPMetricsRecorder:
    """Ventana deslizante de métricas por proveedor/tool."""

    def __init__(self, window_size: int = 200) -> None:
        self._window_size = max(10, window_size)
        self._lock = Lock()
        self._data: Dict[str, _MetricWindow] = {}

    def record_success(self, provider: str, tool: str, latency_ms: float, retries: int) -> None:
        self._record(provider, tool, latency_ms=latency_ms, status="success", retries=retries)

    def record_failure(self, provider: str, tool: str, *, status: str, error_message: str) -> None:
        self._record(provider, tool, status=status, error_message=error_message)

    def snapshot(self) -> List[Dict[str, object]]:
        with self._lock:
            summary: List[Dict[str, object]] = []
            for key, window in self._data.items():
                provider, tool = key.split("::", maxsplit=1)
                latencies = list(window.latencies_ms)
                summary.append(
                    {
                        "provider": provider,
                        "tool": tool,
                        "successes": window.successes,
                        "errors": window.errors,
                        "timeouts": window.timeouts,
                        "avg_latency_ms": round(statistics.fmean(latencies), 2) if latencies else None,
                        "p50_latency_ms": _percentile(latencies, 50),
                        "p95_latency_ms": _percentile(latencies, 95),
                        "p99_latency_ms": _percentile(latencies, 99),
                        "retries": window.retries,
                        "last_error": window.last_error,
                    }
                )
            return summary

    def _record(
        self,
        provider: str,
        tool: str,
        *,
        latency_ms: Optional[float] = None,
        status: str,
        retries: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        key = f"{provider}::{tool}"
        with self._lock:
            window = self._data.get(key)
            if not window:
                window = _MetricWindow(latencies_ms=deque(maxlen=self._window_size))
                self._data[key] = window
            if status == "success" and latency_ms is not None:
                window.latencies_ms.append(latency_ms)
                window.successes += 1
                window.retries += max(0, retries)
            elif status == "timeout":
                window.timeouts += 1
                window.last_error = error_message
            else:
                window.errors += 1
                window.last_error = error_message


def _percentile(values: List[float], percentile: int) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 2)
    values_sorted = sorted(values)
    k = (len(values_sorted) - 1) * (percentile / 100)
    f = int(k)
    c = min(f + 1, len(values_sorted) - 1)
    if f == c:
        return round(values_sorted[int(k)], 2)
    d0 = values_sorted[f] * (c - k)
    d1 = values_sorted[c] * (k - f)
    return round(d0 + d1, 2)
