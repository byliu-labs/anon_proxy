from concurrent.futures import ThreadPoolExecutor

from anon_proxy.stats import MaskerStats


def test_snapshot_reports_session_latency_cache_and_canary_rates():
    stats = MaskerStats()
    stats.record_mask(elapsed_ms=1, cache_hit=False, entities=[])
    stats.record_mask(
        elapsed_ms=2,
        cache_hit=True,
        entities=[
            {"source": "ml", "label": "PERSON", "score": 0.9, "len": 5},
            {"source": "canary", "label": "PHONE", "score": 1.0, "len": 12},
        ],
    )
    stats.record_mask(elapsed_ms=3, cache_hit=False, entities=[])
    stats.record_mask(elapsed_ms=4, cache_hit=True, entities=[])
    stats.record_unknown_tokens(2)

    snapshot = stats.snapshot()

    assert snapshot["mask_calls"] == 4
    assert snapshot["mask_cache_hits"] == 2
    assert snapshot["mask_cache_hit_rate"] == 0.5
    assert snapshot["mask_latency_ms"] == {"p50": 2.5, "p95": 3.85, "p99": 3.97}
    assert snapshot["entities_by_label"] == {"PERSON": 1, "PHONE": 1}
    assert snapshot["entities_by_source"] == {"ml": 1, "canary": 1}
    assert snapshot["canary_hits"] == 1
    assert snapshot["canary_hit_rate"] == 0.25
    assert snapshot["unknown_tokens"] == 2


def test_recording_is_thread_safe():
    stats = MaskerStats()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda value: stats.record_mask(
                    elapsed_ms=value, cache_hit=False, entities=[]
                ),
                range(2000),
            )
        )

    assert stats.snapshot()["mask_calls"] == 2000


def test_latency_samples_are_bounded_without_losing_call_count():
    stats = MaskerStats(max_latency_samples=4)

    for value in range(10):
        stats.record_mask(elapsed_ms=value, cache_hit=False, entities=[])

    snapshot = stats.snapshot()
    assert snapshot["mask_calls"] == 10
    assert snapshot["mask_latency_ms"]["p99"] is not None
    assert len(stats._mask_latencies) == 4


def test_snapshot_rolls_up_mask_calls_by_provider():
    stats = MaskerStats()

    stats.record_mask(
        elapsed_ms=10,
        cache_hit=False,
        provider="anthropic",
        entities=[{"source": "ml", "label": "PERSON", "score": 0.9, "len": 5}],
    )
    stats.record_mask(
        elapsed_ms=20,
        cache_hit=False,
        provider="openai",
        entities=[
            {"source": "ml", "label": "PERSON", "score": 0.9, "len": 5},
            {"source": "canary", "label": "EMAIL", "score": 1.0, "len": 17},
        ],
    )

    assert stats.snapshot()["by_provider"] == {
        "anthropic": {
            "mask_calls": 1,
            "entities": 1,
            "canary_hits": 0,
            "mask_latency_ms": {"p50": 10, "p95": 10, "p99": 10},
        },
        "openai": {
            "mask_calls": 1,
            "entities": 2,
            "canary_hits": 1,
            "mask_latency_ms": {"p50": 20, "p95": 20, "p99": 20},
        },
    }
