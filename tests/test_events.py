import io
import json

from anon_proxy.events import EventSink


def test_human_mode_preserves_existing_warning_text():
    stream = io.StringIO()
    sink = EventSink(stream=stream)

    sink.canary_hit(label="EMAIL", text="alice@example.com", action="warn")
    sink.unknown_token("<PERSON_99>")

    assert stream.getvalue() == (
        "warning: canary: EMAIL 'alice@example.com' survived masking\n"
        "warning: unmask: unknown placeholder <PERSON_99> left in response "
        "(model may have invented it)\n"
    )


def test_json_mode_emits_pii_free_canary_and_unknown_token_events():
    stream = io.StringIO()
    sink = EventSink(log_json=True, stream=stream)

    sink.canary_hit(label="EMAIL", text="alice@example.com", action="fix")
    sink.unknown_token("<PERSON_99>")

    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert events == [
        {
            "event": "canary_hit",
            "label": "EMAIL",
            "len": 17,
            "action": "fix",
        },
        {"event": "unmask_unknown_token", "token": "<PERSON_99>"},
    ]
    assert "alice@example.com" not in stream.getvalue()


def test_json_metrics_are_machine_parseable():
    stream = io.StringIO()
    sink = EventSink(log_json=True, stream=stream)

    sink.metrics(provider="openai", e2e=0.25, upstream=0.1)

    assert json.loads(stream.getvalue()) == {
        "event": "metrics",
        "provider": "openai",
        "e2e_ms": 250.0,
        "upstream_ms": 100.0,
        "proxy_ms": 150.0,
        "proxy_pct": 60.0,
    }
