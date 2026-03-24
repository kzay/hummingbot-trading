"""Rolling percentile latency tracker with JSON file output.

Tracks named metrics, computes p50/p95/p99 from a rolling deque of samples,
and periodically flushes a summary to a JSON file.
"""
from __future__ import annotations

import json
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Mapping, MutableMapping, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = (len(sorted_v) - 1) * q
    lower = int(idx)
    upper = lower + 1
    if upper >= len(sorted_v):
        return sorted_v[-1]
    frac = idx - lower
    return sorted_v[lower] * (1 - frac) + sorted_v[upper] * frac


def summarize_latency(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "count": 0}
    return {
        "p50": round(_percentile(samples, 0.50), 3),
        "p95": round(_percentile(samples, 0.95), 3),
        "p99": round(_percentile(samples, 0.99), 3),
        "count": len(samples),
    }


def merge_latency_summaries(
    *sources: Mapping[str, Mapping[str, float]],
) -> dict[str, dict[str, float]]:
    merged: dict[str, dict[str, float]] = {}
    for src in sources:
        for key, val in src.items():
            merged[key] = dict(val)
    return merged


class JsonLatencyTracker:
    """Thread-safe rolling latency tracker that writes JSON summaries."""

    def __init__(
        self,
        path: Path,
        *,
        max_samples: int = 500,
        flush_interval_s: float = 5.0,
    ) -> None:
        self._path = path
        self._max_samples = max_samples
        self._flush_interval_s = flush_interval_s
        self._lock = Lock()
        self._samples_by_metric: dict[str, deque[float]] = {}
        self._last_values_ms: dict[str, float] = {}
        self._last_flush_ts: float = time.monotonic()

    def observe(self, metric: str, value_ms: float) -> None:
        with self._lock:
            if metric not in self._samples_by_metric:
                self._samples_by_metric[metric] = deque(maxlen=self._max_samples)
            self._samples_by_metric[metric].append(value_ms)
            self._last_values_ms[metric] = value_ms

    def snapshot(
        self, extra: Optional[Mapping[str, object]] = None
    ) -> dict[str, object]:
        with self._lock:
            data: dict[str, object] = {"_ts": _utc_now()}
            for metric, samples in self._samples_by_metric.items():
                summary = summarize_latency(list(samples))
                for stat, val in summary.items():
                    data[f"{metric}_{stat}"] = val
            if self._last_values_ms:
                data["_last_values_ms"] = dict(self._last_values_ms)
            if extra:
                data.update(extra)
        return data

    def flush(
        self,
        extra: Optional[Mapping[str, object]] = None,
        force: bool = False,
    ) -> Optional[Path]:
        now = time.monotonic()
        if not force and (now - self._last_flush_ts) < self._flush_interval_s:
            return None
        self._last_flush_ts = now
        data = self.snapshot(extra=extra)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2, default=str))
        return self._path
