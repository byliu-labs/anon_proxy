"""Thread-safe, PII-free detection metrics for one proxy process."""

from __future__ import annotations

import math
import threading
from collections import Counter


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    value = ordered[lower]
    if lower != upper:
        value += (ordered[upper] - value) * (rank - lower)
    return round(value, 3)


class MaskerStats:
    """Aggregate counts and latency samples without retaining detected text."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mask_latencies: list[float] = []
        self._mask_cache_hits = 0
        self._entities_by_label: Counter[str] = Counter()
        self._entities_by_source: Counter[str] = Counter()
        self._canary_hits = 0
        self._canary_calls = 0
        self._unknown_tokens = 0

    def record_mask(
        self, *, elapsed_ms: float, cache_hit: bool, entities: list[dict]
    ) -> None:
        with self._lock:
            self._mask_latencies.append(elapsed_ms)
            self._mask_cache_hits += cache_hit
            self._canary_calls += any(e["source"] == "canary" for e in entities)
            for entity in entities:
                self._entities_by_label[entity["label"]] += 1
                self._entities_by_source[entity["source"]] += 1
                self._canary_hits += entity["source"] == "canary"

    def record_unknown_tokens(self, count: int) -> None:
        with self._lock:
            self._unknown_tokens += count

    def snapshot(self) -> dict:
        with self._lock:
            calls = len(self._mask_latencies)
            return {
                "mask_calls": calls,
                "mask_cache_hits": self._mask_cache_hits,
                "mask_cache_hit_rate": _rate(self._mask_cache_hits, calls),
                "mask_latency_ms": {
                    "p50": _percentile(self._mask_latencies, 0.50),
                    "p95": _percentile(self._mask_latencies, 0.95),
                },
                "entities_by_label": dict(self._entities_by_label),
                "entities_by_source": dict(self._entities_by_source),
                "canary_hits": self._canary_hits,
                "canary_hit_rate": _rate(self._canary_calls, calls),
                "unknown_tokens": self._unknown_tokens,
            }


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0
