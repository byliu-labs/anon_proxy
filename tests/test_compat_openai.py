from __future__ import annotations

from anon_proxy.regex_detector import RegexDetector
from tests.support.mock_upstream import (
    assert_masked_roundtrip,
    fixture_json,
    fixture_text,
    proxy_client,
    record_route,
)


def _masker(make_masker):
    return make_masker(extra_detectors=[RegexDetector({"PERSON": r"\bAlice\b"})])


def test_openai_chat_non_streaming_roundtrip_and_url(make_masker):
    client, upstream = proxy_client(
        _masker(make_masker),
        routes=[
            record_route(
                "POST",
                "/v1/chat/completions",
                json_body=fixture_json("openai", "chat_basic.response.json"),
            )
        ],
    )

    with client:
        response = client.post(
            "/openai/v1/chat/completions",
            json=fixture_json("openai", "chat_basic.request.json"),
        )

    assert response.status_code == 200
    assert upstream.requests[0].url == "https://api.openai.com/v1/chat/completions"
    assert_masked_roundtrip(
        upstream.requests[0].body,
        response.content,
        raw="Alice",
        token="<PERSON_1>",
    )


def test_openai_chat_streaming_roundtrip(make_masker):
    client, upstream = proxy_client(
        _masker(make_masker),
        routes=[
            record_route(
                "POST",
                "/v1/chat/completions",
                sse=fixture_text("openai", "chat_basic.response.sse.txt"),
            )
        ],
    )
    request = fixture_json("openai", "chat_basic.request.json")
    request["stream"] = True

    with client:
        response = client.post("/openai/v1/chat/completions", json=request)

    assert response.status_code == 200
    assert_masked_roundtrip(
        upstream.requests[0].body,
        response.content,
        raw="Alice",
        token="<PERSON_1>",
    )


def test_openai_chat_error_passthrough_preserves_status_and_body(make_masker):
    client, upstream = proxy_client(
        _masker(make_masker),
        routes=[
            record_route(
                "POST",
                "/v1/chat/completions",
                json_body={"error": {"message": "rate limited"}},
                status=429,
            )
        ],
    )

    with client:
        response = client.post(
            "/openai/v1/chat/completions",
            json=fixture_json("openai", "chat_basic.request.json"),
        )

    assert response.status_code == 429
    assert response.json() == {"error": {"message": "rate limited"}}
    assert b"Alice" not in upstream.requests[0].body
    assert b"<PERSON_1>" in upstream.requests[0].body


def test_openai_responses_non_streaming_roundtrip_and_system_injection(make_masker):
    client, upstream = proxy_client(
        _masker(make_masker),
        system_inject=True,
        routes=[
            record_route(
                "POST",
                "/v1/responses",
                json_body=fixture_json("openai", "responses_basic.response.json"),
            )
        ],
    )

    with client:
        response = client.post(
            "/openai/v1/responses",
            json=fixture_json("openai", "responses_basic.request.json"),
        )

    assert response.status_code == 200
    assert b'"instructions"' in upstream.requests[0].body
    assert_masked_roundtrip(
        upstream.requests[0].body,
        response.content,
        raw="Alice",
        token="<PERSON_1>",
    )


def test_openai_responses_streaming_roundtrip(make_masker):
    client, upstream = proxy_client(
        _masker(make_masker),
        routes=[
            record_route(
                "POST",
                "/v1/responses",
                sse=fixture_text("openai", "responses_basic.response.sse.txt"),
            )
        ],
    )
    request = fixture_json("openai", "responses_basic.request.json")
    request["stream"] = True

    with client:
        response = client.post("/openai/v1/responses", json=request)

    assert response.status_code == 200
    assert_masked_roundtrip(
        upstream.requests[0].body,
        response.content,
        raw="Alice",
        token="<PERSON_1>",
    )
