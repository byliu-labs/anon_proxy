"""Thread-safe, PII-free detection metrics for one proxy process."""

from __future__ import annotations

import math
import threading
from collections import Counter, deque


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

    def __init__(self, *, max_latency_samples: int = 4096) -> None:
        if max_latency_samples <= 0:
            raise ValueError("max_latency_samples must be > 0")
        self._lock = threading.Lock()
        self._mask_latencies: deque[float] = deque(maxlen=max_latency_samples)
        self._mask_calls = 0
        self._mask_cache_hits = 0
        self._entities_by_label: Counter[str] = Counter()
        self._entities_by_source: Counter[str] = Counter()
        self._by_provider: dict[str, dict] = {}
        self._canary_hits = 0
        self._canary_calls = 0
        self._unknown_tokens = 0

    def record_mask(
        self,
        *,
        elapsed_ms: float,
        cache_hit: bool,
        entities: list[dict],
        provider: str | None = None,
    ) -> None:
        with self._lock:
            self._mask_calls += 1
            self._mask_latencies.append(elapsed_ms)
            self._mask_cache_hits += cache_hit
            self._canary_calls += any(e["source"] == "canary" for e in entities)
            if provider is not None:
                provider_stats = self._by_provider.setdefault(
                    provider,
                    {
                        "mask_calls": 0,
                        "entities": 0,
                        "canary_hits": 0,
                        "latencies": deque(maxlen=self._mask_latencies.maxlen),
                    },
                )
                provider_stats["mask_calls"] += 1
                provider_stats["entities"] += len(entities)
                provider_stats["latencies"].append(elapsed_ms)
            for entity in entities:
                self._entities_by_label[entity["label"]] += 1
                self._entities_by_source[entity["source"]] += 1
                self._canary_hits += entity["source"] == "canary"
                if provider is not None and entity["source"] == "canary":
                    self._by_provider[provider]["canary_hits"] += 1

    def record_unknown_tokens(self, count: int) -> None:
        with self._lock:
            self._unknown_tokens += count

    def snapshot(self) -> dict:
        with self._lock:
            calls = self._mask_calls
            latencies = list(self._mask_latencies)
            return {
                "mask_calls": calls,
                "mask_cache_hits": self._mask_cache_hits,
                "mask_cache_hit_rate": _rate(self._mask_cache_hits, calls),
                "mask_latency_ms": {
                    "p50": _percentile(latencies, 0.50),
                    "p95": _percentile(latencies, 0.95),
                    "p99": _percentile(latencies, 0.99),
                },
                "entities_by_label": dict(self._entities_by_label),
                "entities_by_source": dict(self._entities_by_source),
                "by_provider": {
                    provider: {
                        "mask_calls": values["mask_calls"],
                        "entities": values["entities"],
                        "canary_hits": values["canary_hits"],
                        "mask_latency_ms": {
                            "p50": _percentile(list(values["latencies"]), 0.50),
                            "p95": _percentile(list(values["latencies"]), 0.95),
                            "p99": _percentile(list(values["latencies"]), 0.99),
                        },
                    }
                    for provider, values in self._by_provider.items()
                },
                "canary_hits": self._canary_hits,
                "canary_hit_rate": _rate(self._canary_calls, calls),
                "unknown_tokens": self._unknown_tokens,
            }


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0
