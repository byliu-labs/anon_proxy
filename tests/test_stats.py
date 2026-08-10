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
    assert snapshot["mask_latency_ms"] == {"p50": 2.5, "p95": 3.85}
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
