from __future__ import annotations

from anon_proxy.regex_detector import RegexDetector
from tests.support.mock_upstream import (
    assert_masked_roundtrip,
    fixture_json,
    fixture_text,
    proxy_client,
    record_route,
)


def test_anthropic_messages_non_streaming_roundtrip(make_masker):
    masker = make_masker(
        extra_detectors=[RegexDetector({"PERSON": r"\bAlice\b"})],
    )
    client, upstream = proxy_client(
        masker,
        routes=[
            record_route(
                "POST",
                "/v1/messages",
                json_body=fixture_json("anthropic", "messages_basic.response.json"),
            )
        ],
    )

    with client:
        response = client.post(
            "/anthropic/v1/messages",
            json=fixture_json("anthropic", "messages_basic.request.json"),
        )

    assert response.status_code == 200
    assert_masked_roundtrip(
        upstream.requests[0].body,
        response.content,
        raw="Alice",
        token="<PERSON_1>",
    )


def test_anthropic_messages_streaming_roundtrip(make_masker):
    masker = make_masker(
        extra_detectors=[RegexDetector({"PERSON": r"\bAlice\b"})],
    )
    client, upstream = proxy_client(
        masker,
        routes=[
            record_route(
                "POST",
                "/v1/messages",
                sse=fixture_text("anthropic", "messages_basic.response.sse.txt"),
            )
        ],
    )
    request = fixture_json("anthropic", "messages_basic.request.json")
    request["stream"] = True

    with client:
        response = client.post("/anthropic/v1/messages", json=request)

    assert response.status_code == 200
    assert_masked_roundtrip(
        upstream.requests[0].body,
        response.content,
        raw="Alice",
        token="<PERSON_1>",
    )


def test_anthropic_multi_turn_reuses_same_placeholder(make_masker):
    masker = make_masker(
        extra_detectors=[RegexDetector({"PERSON": r"\bAlice\b"})],
    )
    client, upstream = proxy_client(
        masker,
        routes=[
            record_route(
                "POST",
                "/v1/messages",
                json_body=fixture_json("anthropic", "messages_basic.response.json"),
            )
        ],
    )

    with client:
        first = client.post(
            "/anthropic/v1/messages",
            json=fixture_json("anthropic", "messages_basic.request.json"),
        )
        second = client.post(
            "/anthropic/v1/messages",
            json={
                "model": "claude-3-5-sonnet",
                "messages": [{"role": "user", "content": "Email Alice later"}],
            },
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert b"<PERSON_1>" in upstream.requests[0].body
    assert b"<PERSON_1>" in upstream.requests[1].body
    assert b"<PERSON_2>" not in upstream.requests[1].body


def test_anthropic_error_passthrough_preserves_status_and_body(make_masker):
    masker = make_masker(
        extra_detectors=[RegexDetector({"PERSON": r"\bAlice\b"})],
    )
    client, upstream = proxy_client(
        masker,
        routes=[
            record_route(
                "POST",
                "/v1/messages",
                json_body={"error": {"type": "rate_limit_error", "message": "slow"}},
                status=429,
            )
        ],
    )

    with client:
        response = client.post(
            "/anthropic/v1/messages",
            json=fixture_json("anthropic", "messages_basic.request.json"),
        )

    assert response.status_code == 429
    assert response.json() == {"error": {"type": "rate_limit_error", "message": "slow"}}
    assert b"Alice" not in upstream.requests[0].body
    assert b"<PERSON_1>" in upstream.requests[0].body


def test_anthropic_count_tokens_masks_history(make_masker):
    masker = make_masker(
        extra_detectors=[RegexDetector({"PERSON": r"\bAlice\b"})],
    )
    client, upstream = proxy_client(
        masker,
        routes=[
            record_route(
                "POST",
                "/v1/messages/count_tokens",
                json_body={"input_tokens": 17},
            )
        ],
    )

    with client:
        response = client.post(
            "/anthropic/v1/messages/count_tokens",
            json=fixture_json("anthropic", "messages_basic.request.json"),
        )

    assert response.status_code == 200
    assert response.json() == {"input_tokens": 17}
    assert b"Alice" not in upstream.requests[0].body
    assert b"<PERSON_1>" in upstream.requests[0].body
