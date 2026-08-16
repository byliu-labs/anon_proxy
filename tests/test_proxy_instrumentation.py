import json
import io

import httpx
from starlette.testclient import TestClient

from anon_proxy.capture import Capturer
from anon_proxy.events import EventSink
from anon_proxy.masker import Masker
from anon_proxy.metrics import ProxyMetrics
from anon_proxy.server import build_app


class _StubFilter:
    def detect(self, text):
        from anon_proxy.privacy_filter import PIIEntity

        start = text.find("Alice")
        if start == -1:
            return []
        return [
            PIIEntity(
                start=start,
                end=start + 5,
                label="PERSON",
                text="Alice",
                score=0.99,
            )
        ]


def _anthropic_response():
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello <PERSON_1>"}],
            "usage": {"input_tokens": 10, "output_tokens": 25},
        },
    )


def _openai_response():
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        json={
            "id": "chatcmpl_1",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello <PERSON_1>"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        },
    )


def _client_with_upstream(metrics, masker, handler):
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    app = build_app(masker=masker, metrics=metrics, http_client=http_client)
    return TestClient(app)


def test_successful_request_records_metrics():
    metrics = ProxyMetrics(started_at=0.0)
    masker = Masker(filter=_StubFilter())
    client = _client_with_upstream(metrics, masker, lambda req: _anthropic_response())

    with client:
        resp = client.post(
            "/anthropic/v1/messages",
            headers={"user-agent": "claude-cli/1.2.3 (external, cli)"},
            json={
                "model": "claude-3",
                "messages": [{"role": "user", "content": "Call Alice now"}],
            },
        )

    snap = metrics.snapshot()
    assert resp.status_code == 200
    assert snap["requests_masked_total"] == 1
    assert snap["entities_masked_total"] == 1
    assert snap["last_client"] == "Claude Code"
    assert snap["tokens_out_total"] == 25


def test_status_exposes_live_detection_stats_after_masked_request():
    metrics = ProxyMetrics(started_at=0.0)
    masker = Masker(filter=_StubFilter())
    client = _client_with_upstream(metrics, masker, lambda req: _anthropic_response())

    with client:
        resp = client.post(
            "/anthropic/v1/messages",
            json={
                "model": "claude-3",
                "messages": [{"role": "user", "content": "Call Alice now"}],
            },
        )
        status = client.get("/_status")

    body = json.loads(status.text)
    assert resp.status_code == 200
    assert status.status_code == 200
    assert body["schema_version"] == 1
    assert body["detection"]["mask_calls"] >= 1
    assert body["detection"]["mask_cache_hit_rate"] == 0.0
    assert body["detection"]["mask_latency_ms"]["p50"] is not None
    assert body["detection"]["mask_latency_ms"]["p95"] is not None
    assert body["detection"]["mask_latency_ms"]["p99"] is not None
    assert body["detection"]["entities_by_label"] == {"PERSON": 1}
    assert body["detection"]["entities_by_source"] == {"ml": 1}


def test_status_breaks_detection_stats_down_by_provider():
    metrics = ProxyMetrics(started_at=0.0)
    masker = Masker(filter=_StubFilter())

    def handler(req):
        if "chat/completions" in str(req.url):
            return _openai_response()
        return _anthropic_response()

    client = _client_with_upstream(metrics, masker, handler)

    with client:
        anthropic = client.post(
            "/anthropic/v1/messages",
            json={
                "model": "claude-3",
                "messages": [{"role": "user", "content": "Call Alice now"}],
            },
        )
        openai = client.post(
            "/openai/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Email Alice later"}],
            },
        )
        status = client.get("/_status")

    by_provider = json.loads(status.text)["detection"]["by_provider"]
    assert anthropic.status_code == 200
    assert openai.status_code == 200
    assert by_provider["anthropic"]["mask_calls"] >= 1
    assert by_provider["anthropic"]["entities"] == 1
    assert by_provider["openai"]["mask_calls"] >= 1
    assert by_provider["openai"]["entities"] == 1


def test_metrics_file_persists_pii_free_rollup_on_shutdown(tmp_path):
    metrics_file = tmp_path / "metrics.jsonl"
    metrics = ProxyMetrics(started_at=0.0)
    masker = Masker(filter=_StubFilter())
    transport = httpx.MockTransport(lambda req: _anthropic_response())
    http_client = httpx.AsyncClient(transport=transport)
    app = build_app(
        masker=masker,
        metrics=metrics,
        http_client=http_client,
        metrics_file=str(metrics_file),
        metrics_file_interval=3600,
    )

    with TestClient(app) as client:
        resp = client.post(
            "/anthropic/v1/messages",
            json={
                "model": "claude-3",
                "messages": [{"role": "user", "content": "Call Alice now"}],
            },
        )

    payloads = [json.loads(line) for line in metrics_file.read_text().splitlines()]
    assert resp.status_code == 200
    assert payloads[-1]["schema_version"] == 1
    assert payloads[-1]["event"] == "metrics_rollup"
    assert payloads[-1]["detection"]["entities_by_label"] == {"PERSON": 1}
    assert "Alice" not in metrics_file.read_text()


def test_metrics_event_and_capture_records_share_request_id(tmp_path):
    capture_path = tmp_path / "capture.jsonl"
    event_stream = io.StringIO()
    metrics = ProxyMetrics(started_at=0.0)
    masker = Masker(filter=_StubFilter())
    transport = httpx.MockTransport(lambda req: _anthropic_response())
    http_client = httpx.AsyncClient(transport=transport)
    app = build_app(
        masker=masker,
        metrics=True,
        proxy_metrics=metrics,
        capture=Capturer(str(capture_path)),
        http_client=http_client,
        event_sink=EventSink(log_json=True, stream=event_stream),
    )

    with TestClient(app) as client:
        first = client.post(
            "/anthropic/v1/messages",
            json={
                "model": "claude-3",
                "messages": [{"role": "user", "content": "Call Alice now"}],
            },
        )
        second = client.post(
            "/anthropic/v1/messages",
            json={
                "model": "claude-3",
                "messages": [{"role": "user", "content": "Email Alice later"}],
            },
        )

    events = [
        json.loads(line)
        for line in event_stream.getvalue().splitlines()
        if json.loads(line)["event"] == "metrics"
    ]
    captures = [json.loads(line) for line in capture_path.read_text().splitlines()]

    assert first.status_code == 200
    assert second.status_code == 200
    assert [event["request_id"] for event in events] == [
        captures[0]["request_id"],
        captures[1]["request_id"],
    ]
    assert captures[0]["request_id"] != captures[1]["request_id"]


def test_masking_error_trips_alarm_and_fails_closed():
    metrics = ProxyMetrics(started_at=0.0)

    class _BoomFilter:
        def detect(self, text):
            raise RuntimeError("detector exploded")

    contacted = {"upstream": False}

    def handler(req):
        contacted["upstream"] = True
        return _anthropic_response()

    client = _client_with_upstream(metrics, Masker(filter=_BoomFilter()), handler)
    with client:
        resp = client.post(
            "/anthropic/v1/messages",
            json={
                "model": "c",
                "messages": [{"role": "user", "content": "hi Alice"}],
            },
        )

    assert resp.status_code == 502
    assert json.loads(resp.text) == {
        "error": "anon-proxy: masking failed; request blocked"
    }
    assert metrics.snapshot()["masking_errors_total"] == 1
    assert contacted["upstream"] is False
