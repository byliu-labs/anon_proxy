from anon_proxy.bench import (
    baseline_failures,
    percentile,
    request_body,
    summarize_times,
    user_text,
)


def test_synthetic_request_body_accumulates_full_history():
    body = request_body(2)

    assert body["model"] == "claude-x"
    assert [message["role"] for message in body["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert "alice.smith@example.com" in user_text(0)
    assert "alice.smith@example.com" not in user_text(1)


def test_percentiles_use_sorted_nearest_rank_values():
    values = [50.0, 10.0, 30.0, 20.0, 40.0]

    assert percentile(values, 50) == 30.0
    assert percentile(values, 90) == 50.0
    assert percentile(values, 99) == 50.0


def test_summarize_times_reports_cold_warm_and_total():
    summary = summarize_times([100.0, 20.0, 40.0, 30.0])

    assert summary == {
        "cold_ms": 100.0,
        "warm_median_ms": 30.0,
        "warm_p95_ms": 40.0,
        "p50_ms": 35.0,
        "p90_ms": 100.0,
        "p99_ms": 100.0,
        "total_ms": 190.0,
    }


def test_baseline_failures_report_degraded_ratio():
    current = {
        "arms": [
            {
                "name": "onnx",
                "summary": {"warm_median_ms": 130.0},
            }
        ]
    }
    baseline = {
        "arms": [
            {
                "name": "onnx",
                "summary": {"warm_median_ms": 100.0},
            }
        ]
    }

    assert baseline_failures(current, baseline, ratio=1.2) == [
        "onnx warm_median_ms 130.000ms exceeds baseline 100.000ms by 1.300x"
    ]


def test_baseline_failures_ignore_missing_baseline_arm():
    current = {"arms": [{"name": "torch", "summary": {"warm_median_ms": 1.0}}]}
    baseline = {"arms": []}

    assert baseline_failures(current, baseline, ratio=1.0) == []
