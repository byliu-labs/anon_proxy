import io
import json
from pathlib import Path

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
    assert events[0] | {"ts": 0} == {
        "schema_version": 1,
        "ts": 0,
        "event": "canary_hit",
        "label": "EMAIL",
        "len": 17,
        "action": "fix",
    }
    assert events[1] | {"ts": 0} == {
        "schema_version": 1,
        "ts": 0,
        "event": "unmask_unknown_token",
        "token": "<PERSON_99>",
    }
    assert isinstance(events[0]["ts"], float)
    assert isinstance(events[1]["ts"], float)
    assert "alice@example.com" not in stream.getvalue()


def test_json_metrics_are_machine_parseable():
    stream = io.StringIO()
    sink = EventSink(log_json=True, stream=stream)

    sink.metrics(provider="openai", e2e=0.25, upstream=0.1)

    event = json.loads(stream.getvalue())
    assert event | {"ts": 0} == {
        "schema_version": 1,
        "ts": 0,
        "event": "metrics",
        "provider": "openai",
        "e2e_ms": 250.0,
        "upstream_ms": 100.0,
        "proxy_ms": 150.0,
        "proxy_pct": 60.0,
    }


def test_all_json_event_types_are_versioned():
    stream = io.StringIO()
    sink = EventSink(log_json=True, stream=stream)

    sink.metrics(provider="anthropic", e2e=0.1, upstream=0.05)
    sink.metrics_summary({"mask_calls": 1})
    sink.canary_hit(label="EMAIL", text="alice@example.com", action="warn")
    sink.unknown_token("<PERSON_99>")

    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert {event["event"] for event in events} == {
        "metrics",
        "metrics_summary",
        "canary_hit",
        "unmask_unknown_token",
    }
    assert all(event["schema_version"] == 1 for event in events)
    assert all(isinstance(event["ts"], float) for event in events)


def test_observability_docs_name_every_event_type():
    docs = Path("docs/observability.md").read_text()

    assert "metrics" in docs
    assert "metrics_summary" in docs
    assert "canary_hit" in docs
    assert "unmask_unknown_token" in docs
