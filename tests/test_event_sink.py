import io
import json

from anon_proxy.event_sink import EventSink


def test_metrics_human_line_matches_existing_shape():
    stream = io.StringIO()
    sink = EventSink(stream=stream, log_json=False)

    sink.metrics(
        provider="anthropic",
        e2e=0.25,
        upstream=0.1,
        usage={"input": 100, "cache_read": 25, "cache_creation": 5},
    )

    out = stream.getvalue()
    assert "[metrics anthropic]" in out
    assert "e2e=250.0ms" in out
    assert "tokens: in=100 cache_read=25 cache_create=5" in out


def test_metrics_json_line_has_no_human_escape_codes():
    stream = io.StringIO()
    sink = EventSink(stream=stream, log_json=True)

    sink.metrics(provider="openai", e2e=0.25, upstream=0.1)

    payload = json.loads(stream.getvalue())
    assert payload == {
        "event": "metrics",
        "provider": "openai",
        "e2e_ms": 250.0,
        "upstream_ms": 100.0,
        "proxy_ms": 150.0,
        "proxy_pct": 60.0,
    }
    assert "\033" not in stream.getvalue()


def test_canary_json_excludes_raw_display_text():
    stream = io.StringIO()
    sink = EventSink(stream=stream, log_json=True)

    sink.canary_hit(provider="anthropic", path="/v1/messages", display_text="Alice")

    payload = json.loads(stream.getvalue())
    assert payload == {
        "event": "canary_hit",
        "provider": "anthropic",
        "path": "/v1/messages",
    }
    assert "Alice" not in stream.getvalue()


def test_unknown_token_json_excludes_raw_display_text():
    stream = io.StringIO()
    sink = EventSink(stream=stream, log_json=True)

    sink.unknown_token(
        provider="anthropic",
        path="/v1/messages",
        label="PERSON",
        display_text="Alice Smith",
    )

    payload = json.loads(stream.getvalue())
    assert payload == {
        "event": "unknown_token",
        "provider": "anthropic",
        "path": "/v1/messages",
        "label": "PERSON",
    }
    assert "Alice" not in stream.getvalue()
